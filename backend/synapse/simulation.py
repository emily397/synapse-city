"""The heartbeat. Each tick: advance the clock, move agents along roads, form
emergent conversations where agents meet, reflect at night, and harvest training
data on each new day. Conversations run as background tasks so the town keeps
moving while models think.
"""
from __future__ import annotations

import asyncio
import os
import random
import time as _time
from pathlib import Path

# While this file exists, a training cycle owns the GPU and the sim rests
# (backend stays up, no model calls). ops/gpu_handover.ps1 creates/removes it.
_TRAINING_LOCK = Path(os.getenv("SYNAPSE_TRAINING_LOCK",
                                r"C:\Users\nirvana\.synapse\TRAINING.lock"))
# Updated every tick; the supervisor restarts the backend if it goes stale.
_SIM_HEARTBEAT = Path(__file__).resolve().parent.parent / "run" / "sim.heartbeat"

from . import harvest, worldgen
from .agent import Agent
from .bus import BUS
from .config import CONFIG
from .db import DB
from .interactions import run_conversation, world_topics
from .proving import ProvingGrounds
from .survival import Survival, weather_for_day
from .world import load_world, load_personas

_INTERACTIVE_KINDS = {"reasoning", "building", "teaching", "debate", "creative",
                      "social", "farming"}


class Simulation:
    def __init__(self):
        self.world = load_world()
        self.db = DB()
        self.agents: dict[str, Agent] = {
            p["id"]: Agent(p, self.world, self.db) for p in load_personas()
        }
        self.judge = next((a for a in self.agents.values() if a.p.get("is_judge")), None)
        self.survival = Survival(self.db, list(self.agents), world=self.world)
        self.proving = ProvingGrounds(self.db)
        from .library import Library
        self.library = Library(self.db)
        self.proving.library = self.library
        self.proving.survival = self.survival
        for a in self.agents.values():
            a.survival = self.survival
        self.rng = random.Random(CONFIG.seed)
        # the town's time survives restarts: continuity of days is continuity
        # of their world
        self.db._run("CREATE TABLE IF NOT EXISTS simstate (k TEXT PRIMARY KEY, v REAL)")
        st = {r["k"]: r["v"] for r in self.db._all("SELECT k, v FROM simstate")}
        self.tick = int(st.get("tick", 0))
        self.minutes = int(st.get("minutes", CONFIG.day_start_hour * 60))
        self.day = int(st.get("day", 1))
        self.generation = int(st.get("generation", 0))   # dataset/harvest version
        self._trained_gens = 0                            # ACTUAL trained cycles
        self.running = False
        self._convos: set[asyncio.Task] = set()
        self._activity: dict[str, int] = {}      # kind -> recent conversation count
        self._last_expand = -CONFIG.world_expand_cooldown
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
                "generation": self._trained_gens}

    def _is_night(self, h: int) -> bool:
        return h >= CONFIG.night_start_hour or h < CONFIG.day_start_hour

    def _stats(self) -> dict:
        s = self.db.counts()
        s["elo"] = self.db.get_elo()
        # honest counters: 'generation' = ACTUAL completed training cycles
        # (run/eval/gen*.json), not harvest snapshots
        try:
            self._trained_gens = len(list(
                (CONFIG.db_file.parent / "eval").glob("gen*.json")))
        except Exception:
            pass
        s["generation"] = self._trained_gens
        s["datasets_harvested"] = self.generation
        s["verified_solves"] = self.db._one(
            "SELECT COALESCE(SUM(pass),0) AS n FROM attempts")["n"] \
            if self.db._one("SELECT name FROM sqlite_master WHERE name='attempts'") \
            else 0
        s["backend"] = CONFIG.llm_backend
        s["eval"] = self.db.latest_eval()
        s["eval_history"] = self.db.eval_history()
        s["districts"] = len(self.world.districts)
        s["gates"] = len(self.world.frontiers)
        s["world_level"] = sum(d.level for d in self.world.districts.values())
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
        self.survival.add_agent(a.id)
        a.survival = self.survival
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
            try:
                if _TRAINING_LOCK.exists():
                    # A training cycle holds the GPU: the town RESTS instead of
                    # going dark. Backend stays up and connected, clock ticks,
                    # avatars drift home — no LLM/embedding calls. Wakes when the
                    # cycle finishes and the lock is released.
                    await self._rest_tick()
                else:
                    await self.step()
                    BUS.publish({"type": "clock", **self._clock()})
                    if self.tick % CONFIG.harvest_interval == 0:
                        await self._harvest()            # live ELO + rolling datasets
                    if self.tick % 5 == 0:
                        BUS.publish({"type": "stats", **self._stats()})
                        for k, v in (("tick", self.tick), ("minutes", self.minutes),
                                     ("day", self.day), ("generation", self.generation)):
                            self.db._upsert("simstate", "k", ["k", "v"], (k, v))
                # liveness heartbeat: the supervisor restarts the backend if this
                # goes stale, so a silent sim death can never freeze the town again
                _SIM_HEARTBEAT.write_text(str(int(_time.time())), encoding="utf-8")
            except Exception:                            # one bad tick must never
                import traceback                          # kill the whole town
                traceback.print_exc()
            await asyncio.sleep(CONFIG.tick_seconds)

    async def _rest_tick(self):
        """GPU-free tick used while a training cycle runs: advance time, drift
        any travellers one hop, keep clients painted — but make NO model calls."""
        self.minutes += CONFIG.minutes_per_tick
        for a in self.agents.values():
            if a.status == "traveling" and a.path:
                nxt = a.path.pop(0)
                a.district = nxt
                a.pos = dict(self.world.districts[nxt].pos)
                BUS.publish({"type": "move", "agent": a.id, "to_district": nxt,
                             "pos": a.pos})
                if not a.path:
                    a.status = "idle"
        BUS.publish({"type": "clock", **self._clock()})
        BUS.publish({"type": "toast", "text": "the town rests while the elders "
                     "study by lamplight..."}) if self.tick % 20 == 0 else None

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

        # bodies first: hunger ticks, meals get eaten, gardens get worked
        events = await self.survival.tick(self.agents, self.tick,
                                          self._is_night(h), self.rng)
        for aid, ev in events:
            a = self.agents.get(aid)
            if a:
                await a.mem.observe(f"Today I {ev}.", self.tick, kind="survival")

        if self._is_night(h):
            await self._night_step()
        else:
            self.survival.wander_animals(self.rng, list(self.world.districts))
            self._move_and_meet()
            self._world_step()

    # ------------------------------------------------------------------ #
    def _move_and_meet(self):
        # 0) morning: anyone still abed gets up (runs only in daytime).
        for a in self.agents.values():
            if a.status == "sleeping":
                a.status = "idle"
                a.cooldown = 0
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
                    self._grant_district_xp(nxt, 1)     # footfall feeds the place
            elif a.cooldown > 0:
                a.cooldown -= 1

        # 2) idle agents at a place: pair up or wander.
        by_district: dict[str, list[Agent]] = {}
        for a in self.agents.values():
            if a.status == "idle" and a.cooldown == 0:
                a.bored += 1                 # idleness itches; stimulus is a drive
                by_district.setdefault(a.district, []).append(a)

        paired: set[str] = set()
        for did, group in by_district.items():
            district = self.world.districts[did]
            if district.kind not in _INTERACTIVE_KINDS:
                continue
            cands = list(group)
            if district.kind == "debate" and self.judge in cands:
                cands.remove(self.judge)          # the magistrate judges, never debates
            # Survival outranks chatter: the hungry-and-broke don't stop to
            # talk anywhere — they work the rows (farming) or head for them.
            cands = [c for c in cands
                     if not (self.survival.hunger(c.id) >= 60
                             and self.survival.food(c.id) == 0)]
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
                # Proving Grounds: an idle mind at a workshop drifts to the
                # puzzle board (execution-verified training fuel).
                if (self.world.districts[a.district].kind == "building"
                        and a.id not in self.proving.busy
                        and self.rng.random() < 0.35):
                    t = asyncio.create_task(
                        self.proving.attempt(a, self.tick, self.rng))
                    self._convos.add(t)
                    t.add_done_callback(self._convos.discard)
                    continue
                # Coin buys land, land lets you build a home: a resident who has
                # saved enough may buy their own plot (a joyful milestone).
                if (not self.survival.owns_land(a.id)
                        and self.survival.coin(a.id) >= 25
                        and self.rng.random() < 0.3):
                    ev = self.survival.maybe_buy_land(a.id, self.agents)
                    if ev:
                        t = asyncio.create_task(
                            a.mem.observe(ev, self.tick, kind="survival"))
                        self._convos.add(t); t.add_done_callback(self._convos.discard)
                        continue
                # Foraging the perimeter gardens: investigating wild foliage can
                # discover new plantable flora for the whole town.
                if (self.world.districts[a.district].kind == "farming"
                        and self.rng.random() < 0.15):
                    async def _forage(ag=a):
                        ev = await self.survival.maybe_forage(ag, self.tick, self.rng)
                        if ev:
                            await ag.mem.observe(ev, self.tick, kind="survival")
                    t = asyncio.create_task(_forage())
                    self._convos.add(t); t.add_done_callback(self._convos.discard)
                    continue
                # Builders: work on your own home (only on land you own) or shore
                # up the district you're in (real XP -> visible level-ups).
                if (a.district == a.p["home"]
                        and self.survival.owns_land(a.id)
                        and self.survival.hunger(a.id) < 60
                        and self.rng.random() < 0.12):
                    ev = self.survival.build_home(a.id, self.agents)
                    if ev:
                        t = asyncio.create_task(
                            a.mem.observe(f"Today I {ev}.", self.tick, kind="survival"))
                        self._convos.add(t)
                        t.add_done_callback(self._convos.discard)
                        continue
                if self.rng.random() < 0.08:
                    self._grant_district_xp(a.district, 2)     # renovation work
                # Invention: a healthy mind at a creative/building bench may
                # author something new into the world (model-written culture).
                if (self.world.districts[a.district].kind in ("creative", "building")
                        and self.survival.hp(a.id) > 60
                        and self.rng.random() < 0.04):
                    async def _inv(ag=a):
                        ev = await self.survival.invent(ag, self.tick)
                        if ev:
                            await ag.mem.observe(f"Today I {ev}", self.tick,
                                                 kind="survival")
                    t = asyncio.create_task(_inv())
                    self._convos.add(t)
                    t.add_done_callback(self._convos.discard)
                    continue
                # A hungry farmer stays at the rows until the crop comes in.
                if (self.world.districts[a.district].kind == "farming"
                        and self.survival.hunger(a.id) >= 60):
                    continue
                # Linger at an interactive spot to give a partner time to arrive.
                if a.district in interactive_here and self.rng.random() < 0.55:
                    continue
                dest = self._choose_destination(a)
                if dest != a.district:
                    a.path = self.world.route(a.district, dest)[1:]
                    a.status = "traveling"

    def _choose_destination(self, a: Agent) -> str:
        # Bias toward the Arena and the agent's home so meetings actually happen.
        # Districts with an unopened gate pull curious agents outward.
        # Hunger overrides wanderlust: hungry townsfolk head for the gardens.
        gate_districts = self.world.frontier_districts()
        hungry = self.survival.hunger(a.id) >= 60 and self.survival.food(a.id) == 0
        # Where the people are: bored residents gravitate to occupied places.
        occupancy: dict[str, int] = {}
        for other in self.agents.values():
            if other.id != a.id and other.status in ("idle", "interacting"):
                occupancy[other.district] = occupancy.get(other.district, 0) + 1
        stir = min(a.bored, 20) / 10.0       # 0..2: restlessness multiplier
        weights = []
        for did, d in self.world.districts.items():
            w = 1.0
            if did == a.p["home"]:
                w += 2.0
            if did == "arena":
                w += 2.5
            if d.kind == "rest":
                w = 0.2
            if did in gate_districts:
                w += 1.2 + 0.8 * stir        # novelty pulls harder on the bored
            if d.kind == "farming":
                w += 12.0 if hungry else 0.8
            # Court hours: afternoons, the town drifts to the arena to argue
            # and watch arguments (this is where preference pairs come from).
            if d.kind == "debate" and 13 <= ((self.minutes // 60) % 24) < 18:
                w += 6.0
            w += min(occupancy.get(did, 0), 3) * (0.8 + stir)   # seek company
            weights.append((did, w))
        r = self.rng.random() * sum(w for _, w in weights)
        acc = 0.0
        for did, w in weights:
            acc += w
            if r <= acc:
                return did
        return a.p["home"]

    # ------------------------------------------------------------------ #
    # The world's own learning loop: places earn XP from real use and level
    # up; curious agents standing at a frontier gate may open it, and the
    # generator grows a district shaped by what the town has been doing.
    def _world_step(self):
        for f in list(self.world.frontiers):
            if len(self.world.districts) >= CONFIG.world_max_districts:
                return
            if self.tick - self._last_expand < CONFIG.world_expand_cooldown:
                return
            here = [a for a in self.agents.values()
                    if a.district == f["from"] and a.status == "idle"]
            for a in here:
                if self.rng.random() < CONFIG.world_curiosity:
                    self._open_gate(f, a)
                    return

    def _open_gate(self, frontier: dict, opener: Agent):
        bundle = worldgen.generate_district(self.world, frontier,
                                            self._activity, self.rng)
        if bundle is None:
            self.world.frontiers.remove(frontier)      # no land that way
            self.world.save()
            return
        self._last_expand = self.tick
        self.world.add_district(**bundle)
        d = bundle["district"]
        BUS.publish({"type": "world_update", "kind": "district_discovered",
                     "district": d, "road": bundle["road"],
                     "frontiers": bundle["frontiers"],
                     "opened": bundle["opened"],
                     "by": opener.public(),
                     "districts_total": len(self.world.districts)})
        BUS.publish({"type": "toast",
                     "text": f"{opener.p['name']} dared the {frontier['name']}: "
                             f"{d['name']} exists now"})
        # The discoverer walks through first.
        opener.path = [d["id"]]
        opener.status = "traveling"

    def _grant_district_xp(self, district_id: str, amount: int):
        new_level = self.world.grant_xp(district_id, amount)
        if new_level:
            d = self.world.districts[district_id]
            BUS.publish({"type": "world_update", "kind": "district_levelup",
                         "district_id": district_id, "level": new_level,
                         "name": d.name, "color": d.color})

    def _start_conversation(self, a: Agent, b: Agent, district):
        a.status = b.status = "interacting"
        a.bored = b.bored = 0                # company scratches the itch
        a.partner, b.partner = b.id, a.id
        self._activity[district.kind] = self._activity.get(district.kind, 0) + 1
        self._grant_district_xp(district.id, 3)
        # the magistrate now scores teaching and building sessions too (~3x fuel)
        judge = (self.judge if district.kind in ("debate", "teaching", "building")
                 else None)

        h = (self.minutes // 60) % 24
        tod = ("early morning" if h < 10 else "midday" if h < 15
               else "late afternoon" if h < 19 else "evening")
        ctx = {
            "weather": self.survival.current_weather(self.day),
            "time_of_day": tod,
            "live_topics": world_topics(self.world, self.survival, self.db,
                                        self.day, self.rng),
            "survival": self.survival,
            "library": self.library,
        }
        if self.survival.event:
            ctx["event"] = (f"The town is in the grip of "
                            f"{self.survival.event['name']} right now.")

        async def _runner():
            try:
                await run_conversation(a, b, district, self.db, self.tick, judge,
                                       ctx=ctx)
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
            elif a.status == "sleeping":
                # night study: minds work by lamplight (guaranteed nightly
                # verified-task quota without stealing daytime social life)
                if (self.rng.random() < 0.10
                        and a.id not in self.proving.busy):
                    t = asyncio.create_task(
                        self.proving.attempt(a, self.tick, self.rng))
                    self._convos.add(t)
                    t.add_done_callback(self._convos.discard)
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
        try:
            await self.library.nightly_distill(self.db, self.day)
        except Exception:
            pass
        await self._harvest()

    async def _harvest(self):
        try:
            await self.library.author_pending(self.agents, self.tick)
        except Exception:
            pass
        gen = await harvest.harvest_cycle(self.db, self.generation, self.agents)
        if gen is not None:
            self.generation = gen.get("generation", self.generation)
            BUS.publish({"type": "generation", **gen})


SIM = Simulation()
