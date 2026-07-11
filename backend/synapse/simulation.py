"""The heartbeat. Each tick: advance the clock, move agents along roads, form
emergent conversations where agents meet, reflect at night, and harvest training
data on each new day. Conversations run as background tasks so the town keeps
moving while models think.
"""
from __future__ import annotations

import asyncio
import random

from . import harvest
from .agent import Agent
from .bus import BUS
from .config import CONFIG
from .db import DB
from .interactions import run_conversation
from .world import load_world, load_personas

_INTERACTIVE_KINDS = {"reasoning", "building", "teaching", "debate", "creative", "social"}


class Simulation:
    def __init__(self):
        self.world = load_world()
        self.db = DB()
        self.agents: dict[str, Agent] = {
            p["id"]: Agent(p, self.world, self.db) for p in load_personas()
        }
        self.judge = next((a for a in self.agents.values() if a.p.get("is_judge")), None)
        self.rng = random.Random(CONFIG.seed)
        self.tick = 0
        self.minutes = CONFIG.day_start_hour * 60
        self.day = 1
        self.generation = 0
        self.running = False
        self._convos: set[asyncio.Task] = set()
        self._seed_elo()

    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "world": self.world.to_dict(),
            "agents": [a.public() for a in self.agents.values()],
            "clock": self._clock(),
            "stats": self._stats(),
        }

    def _clock(self) -> dict:
        h = (self.minutes // 60) % 24
        return {"tick": self.tick, "day": self.day, "hour": h,
                "minute": self.minutes % 60, "night": self._is_night(h),
                "generation": self.generation}

    def _is_night(self, h: int) -> bool:
        return h >= CONFIG.night_start_hour or h < CONFIG.day_start_hour

    def _stats(self) -> dict:
        s = self.db.counts()
        s["elo"] = self.db.get_elo()
        s["generation"] = self.generation
        s["backend"] = CONFIG.llm_backend
        s["eval"] = self.db.latest_eval()
        s["eval_history"] = self.db.eval_history()
        return s

    def _seed_elo(self):
        if not self.db.get_elo():
            for aid in self.agents:
                self.db.set_elo(aid, 1000.0, 0)

    def add_agent(self, persona: dict) -> dict:
        """Spawn a new resident into the live town (a model gets a body and a
        home). Broadcasts so every connected 3D client sees it walk in."""
        if persona["id"] in self.agents:
            raise ValueError(f"agent '{persona['id']}' already exists")
        if persona.get("home") not in self.world.districts:
            persona["home"] = "plaza"
        a = Agent(persona, self.world, self.db)
        self.agents[a.id] = a
        if persona.get("is_judge") and self.judge is None:
            self.judge = a
        self.db.set_elo(a.id, 1000.0, 0)
        BUS.publish({"type": "agent_added", "agent": a.public()})
        BUS.publish({"type": "toast", "text": f"{a.p['name']} moved into town "
                     f"({a.model})"})
        return a.public()

    # ------------------------------------------------------------------ #
    async def run(self):
        self.running = True
        BUS.publish(self.snapshot())
        while self.running:
            await self.step()
            BUS.publish({"type": "clock", **self._clock()})
            if self.tick % CONFIG.harvest_interval == 0:
                await self._harvest()                    # live ELO + rolling datasets
            if self.tick % 5 == 0:
                BUS.publish({"type": "stats", **self._stats()})
            await asyncio.sleep(CONFIG.tick_seconds)

    def stop(self):
        self.running = False

    async def step(self):
        self.tick += 1
        prev_h = (self.minutes // 60) % 24
        self.minutes += CONFIG.minutes_per_tick
        h = (self.minutes // 60) % 24

        # New day rollover -> harvest yesterday's interactions into datasets.
        if h < prev_h:
            self.day += 1
            await self._new_day()

        if self._is_night(h):
            await self._night_step()
        else:
            self._move_and_meet()

    # ------------------------------------------------------------------ #
    def _move_and_meet(self):
        # 1) advance travellers one road hop.
        for a in self.agents.values():
            if a.status == "traveling" and a.path:
                nxt = a.path.pop(0)
                a.district = nxt
                a.pos = dict(self.world.districts[nxt].pos)
                BUS.publish({"type": "move", "agent": a.id, "to_district": nxt,
                             "pos": a.pos})
                if not a.path:
                    a.status = "idle"
                    a.cooldown = 0
            elif a.cooldown > 0:
                a.cooldown -= 1

        # 2) idle agents at a place: pair up or wander.
        by_district: dict[str, list[Agent]] = {}
        for a in self.agents.values():
            if a.status == "idle" and a.cooldown == 0:
                by_district.setdefault(a.district, []).append(a)

        paired: set[str] = set()
        for did, group in by_district.items():
            district = self.world.districts[did]
            if district.kind not in _INTERACTIVE_KINDS:
                continue
            cands = list(group)
            if district.kind == "debate" and self.judge in cands:
                cands.remove(self.judge)          # Juno judges, never debates
            self.rng.shuffle(cands)               # vary who pairs with whom
            if len(cands) >= 2:
                a, b = cands[0], cands[1]
                self._start_conversation(a, b, district)
                paired.update({a.id, b.id})

        # 3) everyone still idle picks a destination (or waits for a partner).
        interactive_here = {d for d, g in by_district.items()
                            if self.world.districts[d].kind in _INTERACTIVE_KINDS}
        for a in self.agents.values():
            if a.status == "idle" and a.cooldown == 0 and a.id not in paired:
                # Linger at an interactive spot to give a partner time to arrive.
                if a.district in interactive_here and self.rng.random() < 0.55:
                    continue
                dest = self._choose_destination(a)
                if dest != a.district:
                    a.path = self.world.route(a.district, dest)[1:]
                    a.status = "traveling"

    def _choose_destination(self, a: Agent) -> str:
        # Bias toward the Arena and the agent's home so meetings actually happen.
        weights = []
        for did, d in self.world.districts.items():
            w = 1.0
            if did == a.p["home"]:
                w += 2.0
            if did == "arena":
                w += 2.5
            if d.kind == "rest":
                w = 0.2
            weights.append((did, w))
        r = self.rng.random() * sum(w for _, w in weights)
        acc = 0.0
        for did, w in weights:
            acc += w
            if r <= acc:
                return did
        return a.p["home"]

    def _start_conversation(self, a: Agent, b: Agent, district):
        a.status = b.status = "interacting"
        a.partner, b.partner = b.id, a.id
        judge = self.judge if district.kind == "debate" else None

        async def _runner():
            try:
                await run_conversation(a, b, district, self.db, self.tick, judge)
            finally:
                for x in (a, b):
                    x.status = "idle"
                    x.partner = None
                    x.cooldown = 1

        task = asyncio.create_task(_runner())
        self._convos.add(task)
        task.add_done_callback(self._convos.discard)

    # ------------------------------------------------------------------ #
    async def _night_step(self):
        for a in self.agents.values():
            if a.status == "interacting":
                continue
            home = a.p["home"]
            if a.district != home and a.status != "traveling":
                a.path = self.world.route(a.district, home)[1:]
                a.status = "traveling"
            elif a.status == "traveling" and a.path:
                nxt = a.path.pop(0)
                a.district = nxt
                a.pos = dict(self.world.districts[nxt].pos)
                BUS.publish({"type": "move", "agent": a.id, "to_district": nxt, "pos": a.pos})
                if not a.path:
                    a.status = "sleeping"
            elif a.district == home:
                a.status = "sleeping"
                insight = await a.mem.reflect(a.p, self.tick)
                if insight:
                    BUS.publish({"type": "reflect", "agent": a.public(), "insight": insight})

    async def _new_day(self):
        # wake everyone
        for a in self.agents.values():
            if a.status == "sleeping":
                a.status = "idle"
                a.cooldown = 0
        await self._harvest()

    async def _harvest(self):
        gen = await harvest.harvest_cycle(self.db, self.generation, self.agents)
        if gen is not None:
            self.generation = gen.get("generation", self.generation)
            BUS.publish({"type": "generation", **gen})


SIM = Simulation()
