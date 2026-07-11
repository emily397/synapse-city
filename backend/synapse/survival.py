"""Embodied survival: hunger, growing food, and the sensed world.

Residents are flesh-and-blood townsfolk. They get hungry, plant and tend crops
in the gardens, harvest (which can fail), eat from their own stores, and share
with starving neighbours. Survival pressure makes movement and conversation
goal-directed, and every event becomes a memory the dialogue engine retrieves —
so the stakes show up in what they say, and in the harvested training data.

All state persists in the `survival` and `plots` tables, so hunger and crops
survive a restart.
"""
from __future__ import annotations

import os
import random

from .bus import BUS
from .db import DB

# --- tuning ------------------------------------------------------------- #
HUNGER_PER_TICK = 0.45         # ~65/day at 144 ticks/day: must eat ~2x a day
EAT_AT = 45                    # eat when hungrier than this (if food in hand)
STARVING_AT = 80               # starving: drop everything, seek food
MEAL_RESTORES = 35
GROW_TICKS = 10                # plant -> ripe; short enough to finish a visit
TEND_BONUS = 3                 # each tending shaves ticks off growth
WITHER_CHANCE = 0.15           # a crop can fail: real loss, felt
YIELD_RANGE = (2, 4)
START_HUNGER = 25.0
START_FOOD = 3

WEATHERS = ["clear and bright", "grey with soft rain", "windy, dust on the road",
            "hot and still", "cool with low fog", "crisp, smell of coming rain"]

# Spontaneous weather events: rare, random, and consequential. Crops die, food
# spoils, buildings take damage — and every loss becomes a felt memory.
EVENT_CHANCE = float(os.getenv("SYNAPSE_WEATHER_EVENT_CHANCE", "0.004"))  # per tick
WEATHER_EVENTS = [
    {"name": "a black-cloud storm", "duration": 8,
     "weather": "a storm: hammering rain, wind tearing at shutters, thunder overhead",
     "crop_kill": 0.6, "food_spoil": 0.25, "damage": True},
    {"name": "a sudden hailstorm", "duration": 5,
     "weather": "hail: ice rattling off roofs, everyone running for doorways",
     "crop_kill": 0.8, "food_spoil": 0.10, "damage": False},
    {"name": "a scorching heatwave", "duration": 12,
     "weather": "a heatwave: the air shimmers, wells run warm, no shade helps",
     "crop_kill": 0.35, "food_spoil": 0.35, "damage": False},
    {"name": "a howling windstorm", "duration": 6,
     "weather": "a windstorm: dust and torn thatch in the air, carts overturned",
     "crop_kill": 0.25, "food_spoil": 0.0, "damage": True},
    {"name": "an early frost", "duration": 10,
     "weather": "a hard frost: white rime on the rows, breath fogging",
     "crop_kill": 0.7, "food_spoil": 0.0, "damage": False},
]

SENSES = {
    "farming":   "loam under your nails, rows of green shoots, the smell of turned earth",
    "reasoning": "shelves of jars and instruments, chalk dust, a kettle somewhere",
    "building":  "hammer-rings, hot metal, sawdust drifting in the light",
    "teaching":  "slate boards, benches worn smooth, children's chalk marks",
    "debate":    "the stone court, echoing voices, townsfolk leaning on the rail",
    "creative":  "paint pots and loom threads, colour everywhere, a lute out of tune",
    "social":    "market stalls, bread and woodsmoke, neighbours calling greetings",
    "rest":      "lamplit doorways, supper smells, the day settling down",
}


def weather_for_day(day: int) -> str:
    return WEATHERS[random.Random(day * 7919).randrange(len(WEATHERS))]


def _spoil(n: int, pct: float, rng: random.Random) -> int:
    """How many of n food portions spoil at probability pct each."""
    return sum(1 for _ in range(n) if rng.random() < pct)


def hunger_phrase(h: float) -> str:
    if h >= STARVING_AT:
        return "you are STARVING; your stomach aches and you can think of little but food"
    if h >= EAT_AT:
        return "you are hungry; a meal would be welcome"
    if h >= 20:
        return "you are fed well enough"
    return "you are comfortably full"


class Survival:
    def __init__(self, db: DB, agent_ids: list[str], world=None):
        self.db = db
        self.world = world
        self.event: dict | None = None       # active weather event
        self.event_until = 0
        db.ensure_survival_tables()
        self.state: dict[str, dict] = {}
        for aid in agent_ids:
            row = db.get_survival(aid)
            if row is None:
                row = {"agent": aid, "hunger": START_HUNGER, "food": START_FOOD,
                       "harvests": 0, "withers": 0, "meals_shared": 0}
                db.set_survival(**row)
            self.state[aid] = row

    # ---------------------------------------------------------------- #
    def add_agent(self, aid: str):
        if aid not in self.state:
            row = {"agent": aid, "hunger": START_HUNGER, "food": START_FOOD,
                   "harvests": 0, "withers": 0, "meals_shared": 0}
            self.db.set_survival(**row)
            self.state[aid] = row

    def hunger(self, aid: str) -> float:
        return self.state.get(aid, {}).get("hunger", 0.0)

    def food(self, aid: str) -> int:
        return self.state.get(aid, {}).get("food", 0)

    def is_starving(self, aid: str) -> bool:
        return self.hunger(aid) >= STARVING_AT

    def status_line(self, aid: str) -> str:
        s = self.state[aid]
        food = s["food"]
        stores = (f"you carry {food} portion{'s' if food != 1 else ''} of food"
                  if food else "your food pouch is empty")
        return f"{hunger_phrase(s['hunger'])}; {stores}"

    # ---------------------------------------------------------------- #
    def current_weather(self, day: int) -> str:
        if self.event:
            return self.event["weather"]
        return weather_for_day(day)

    def _maybe_weather_event(self, agents: dict, tick: int,
                             rng: random.Random) -> list[tuple[str, str]]:
        """Spontaneous, RNG-driven weather with real consequences. Rare by
        design (EVENT_CHANCE/tick); never stacks with an active event."""
        out: list[tuple[str, str]] = []
        if self.event and tick >= self.event_until:
            BUS.publish({"type": "toast",
                         "text": f"{self.event['name'].capitalize()} has passed ⛅"})
            self.event = None
        if self.event or rng.random() >= EVENT_CHANCE:
            return out
        ev = rng.choice(WEATHER_EVENTS)
        self.event = ev
        self.event_until = tick + ev["duration"]
        BUS.publish({"type": "toast", "text": f"⚡ {ev['name'].capitalize()} hits the town!"})

        # crops: growing plots can be flattened
        for aid in list(self.state):
            plot = self.db.get_plot(aid)
            if plot and plot["state"] == "growing" and rng.random() < ev["crop_kill"]:
                self.db.set_plot(aid, "empty", 0)
                self.state[aid]["withers"] += 1
                out.append((aid, f"lost their growing crop to {ev['name']}"))
        # supplies: carried food can spoil
        if ev["food_spoil"] > 0:
            for aid, s in self.state.items():
                lost = _spoil(s["food"], ev["food_spoil"], rng)
                if lost:
                    s["food"] = max(0, s["food"] - lost)
                    self.db.set_survival(**s)
                    out.append((aid, f"had {lost} portion{'s' if lost != 1 else ''} "
                                     f"of food spoiled by {ev['name']}"))
        # buildings: a random district takes damage the town will talk about
        if ev["damage"] and self.world is not None:
            candidates = [d for d in self.world.districts.values()
                          if d.kind not in ("rest",)]
            if candidates:
                d = rng.choice(candidates)
                d.xp = max(0, d.xp - 6)
                try:
                    self.world.save()
                except Exception:
                    pass
                BUS.publish({"type": "toast",
                             "text": f"{ev['name'].capitalize()} damaged {d.name} 🏚️"})
                for aid, a in agents.items():
                    if a.district == d.id:
                        out.append((aid, f"saw {ev['name']} tear into {d.name} "
                                         f"around them"))
        return out

    # ---------------------------------------------------------------- #
    async def tick(self, agents: dict, tick: int, is_night: bool, rng: random.Random):
        """One survival step for the whole town. Returns list of (agent, event
        text) so the sim can turn them into memories/speech."""
        events: list[tuple[str, str]] = []
        events.extend(self._maybe_weather_event(agents, tick, rng))
        for aid, a in agents.items():
            s = self.state.setdefault(aid, {"agent": aid, "hunger": START_HUNGER,
                                            "food": START_FOOD, "harvests": 0,
                                            "withers": 0, "meals_shared": 0})
            was_starving = s["hunger"] >= STARVING_AT
            s["hunger"] = min(100.0, s["hunger"] + (HUNGER_PER_TICK * (0.4 if is_night else 1.0)))

            # eat when hungry and carrying food
            if s["hunger"] >= EAT_AT and s["food"] > 0:
                s["food"] -= 1
                s["hunger"] = max(0.0, s["hunger"] - MEAL_RESTORES)
                events.append((aid, "ate a meal from their pouch"))
            elif not was_starving and s["hunger"] >= STARVING_AT:
                events.append((aid, "is starving and needs to find food"))
                BUS.publish({"type": "toast",
                             "text": f"{a.p['name']} is starving 🥀"})

            # work the gardens when standing in a farming district
            district = getattr(a, "district", None)
            if district and a.status == "idle" and self._district_kind(a) == "farming":
                ev = self._work_plot(aid, a, tick, rng)
                if ev:
                    events.append((aid, ev))
            self.db.set_survival(**s)
        return events

    def _district_kind(self, a) -> str:
        try:
            return self.world.districts[a.district].kind
        except Exception:
            return ""

    def _work_plot(self, aid: str, a, tick: int, rng: random.Random) -> str | None:
        plot = self.db.get_plot(aid)
        s = self.state[aid]
        if plot is None or plot["state"] == "empty":
            self.db.set_plot(aid, "growing", tick + GROW_TICKS)
            BUS.publish({"type": "toast", "text": f"{a.p['name']} planted a crop 🌱"})
            return "planted a crop in the gardens"
        if plot["state"] == "growing":
            if tick >= plot["ready_tick"]:
                if rng.random() < WITHER_CHANCE:
                    self.db.set_plot(aid, "empty", 0)
                    s["withers"] += 1
                    BUS.publish({"type": "toast",
                                 "text": f"{a.p['name']}'s crop withered 🥀"})
                    return "found their crop withered and lost the planting"
                n = rng.randint(*YIELD_RANGE)
                s["food"] += n
                s["harvests"] += 1
                self.db.set_plot(aid, "empty", 0)
                BUS.publish({"type": "toast",
                             "text": f"{a.p['name']} harvested {n} portions 🌾"})
                return f"harvested {n} portions of food from their plot"
            # tend: growing goes faster
            self.db.set_plot(aid, "growing", max(tick + 1, plot["ready_tick"] - TEND_BONUS))
            return None                                   # tending is quiet work
        return None

    # ---------------------------------------------------------------- #
    def maybe_share(self, giver_id: str, taker_id: str, agents: dict) -> str | None:
        """Called when two residents meet: a fed neighbour shares with a
        starving one. Generosity with a cost — real social texture."""
        g, t = self.state.get(giver_id), self.state.get(taker_id)
        if not g or not t:
            return None
        if t["hunger"] >= STARVING_AT and g["food"] >= 2:
            g["food"] -= 1
            t["food"] += 1
            g["meals_shared"] += 1
            self.db.set_survival(**g)
            self.db.set_survival(**t)
            gn = agents[giver_id].p["name"]
            tn = agents[taker_id].p["name"]
            BUS.publish({"type": "toast", "text": f"{gn} shared food with {tn} 🍞"})
            return f"{gn} shared a portion of food with {tn}, who was starving"
        return None

    def public(self, aid: str) -> dict:
        s = self.state.get(aid, {})
        return {"hunger": round(s.get("hunger", 0.0), 1), "food": s.get("food", 0),
                "harvests": s.get("harvests", 0), "withers": s.get("withers", 0),
                "meals_shared": s.get("meals_shared", 0)}
