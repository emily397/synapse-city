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


GOODS = ["a wool blanket", "a coil of rope", "lantern oil", "iron nails",
         "dried herbs", "a clay jug", "good flint", "a sharpening stone"]

# Wild foliage a resident might identify while foraging the perimeter. Finding
# a NEW one adds it to the town's plantable seed stock — the world's flora grows
# because they investigated it.
WILD_FLORA = ["bittercress", "marsh samphire", "hedge garlic", "fat-hen greens",
              "sorrel", "pignut", "sea beet", "nettle tops", "wild leek",
              "hawthorn haw", "burdock root", "chicory"]

ANIMALS = [("sheep", "gardens"), ("sheep", "gardens"), ("goat", "gardens"),
           ("goat", "halcyon_mill"), ("hen", "plaza"), ("hen", "plaza"),
           ("pig", "gardens"), ("dog", "plaza"), ("cat", "school"),
           ("crow", "vesper_observatory")]

START_COIN = 10.0
LAND_PRICE = 25.0


class Survival:
    def __init__(self, db: DB, agent_ids: list[str], world=None):
        self.db = db
        self.world = world
        self.event: dict | None = None       # active weather event
        self.event_until = 0
        self.drought_until = 0                # sustained disaster: crops keep dying
        self._now_tick = 0
        db.ensure_survival_tables()
        db._run("CREATE TABLE IF NOT EXISTS goods ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, item TEXT)"
                if not db.pg else
                "CREATE TABLE IF NOT EXISTS goods ("
                " id SERIAL PRIMARY KEY, agent TEXT, item TEXT)")
        db._run("CREATE TABLE IF NOT EXISTS health ("
                " agent TEXT PRIMARY KEY, hp REAL DEFAULT 100)")
        db._run("CREATE TABLE IF NOT EXISTS homes ("
                " agent TEXT PRIMARY KEY, quality REAL DEFAULT 0)")
        db._run("CREATE TABLE IF NOT EXISTS townstore (k TEXT PRIMARY KEY, v REAL)")
        db._run("CREATE TABLE IF NOT EXISTS wallet ("
                " agent TEXT PRIMARY KEY, coin REAL DEFAULT 0, joy REAL DEFAULT 50,"
                " owns_land INTEGER DEFAULT 0)")
        db._run("CREATE TABLE IF NOT EXISTS flora ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, name TEXT,"
                " tick INTEGER)" if not db.pg else
                "CREATE TABLE IF NOT EXISTS flora ("
                " id SERIAL PRIMARY KEY, agent TEXT, name TEXT, tick INTEGER)")
        db._run("CREATE TABLE IF NOT EXISTS animals (id TEXT PRIMARY KEY,"
                " kind TEXT, district TEXT)")
        self._seed_animals()
        r = db._one("SELECT v FROM townstore WHERE k='drought_until'")
        if r:
            self.drought_until = int(r["v"])   # survive restarts / train cycles
        r = db._one("SELECT v FROM townstore WHERE k='omen_until'")
        self.omen_until = int(r["v"]) if r else 0   # sky-omen is fresh talk for a while
        db._run("CREATE TABLE IF NOT EXISTS inventions ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, name TEXT,"
                " what TEXT, tick INTEGER)" if not db.pg else
                "CREATE TABLE IF NOT EXISTS inventions ("
                " id SERIAL PRIMARY KEY, agent TEXT, name TEXT, what TEXT,"
                " tick INTEGER)")
        db._run("CREATE TABLE IF NOT EXISTS relations ("
                " pair TEXT PRIMARY KEY, score REAL DEFAULT 0)")
        self.state: dict[str, dict] = {}
        for aid in agent_ids:
            row = db.get_survival(aid)
            if row is None:
                row = {"agent": aid, "hunger": START_HUNGER, "food": START_FOOD,
                       "harvests": 0, "withers": 0, "meals_shared": 0}
                db.set_survival(**row)
            self.state[aid] = row
            self._seed_goods(aid)

    # ---------------------------------------------------------------- #
    def add_agent(self, aid: str):
        if aid not in self.state:
            row = {"agent": aid, "hunger": START_HUNGER, "food": START_FOOD,
                   "harvests": 0, "withers": 0, "meals_shared": 0}
            self.db.set_survival(**row)
            self.state[aid] = row
            self._seed_goods(aid)

    def hunger(self, aid: str) -> float:
        return self.state.get(aid, {}).get("hunger", 0.0)

    def food(self, aid: str) -> int:
        return self.state.get(aid, {}).get("food", 0)

    def is_starving(self, aid: str) -> bool:
        return self.hunger(aid) >= STARVING_AT

    # --- money, land, and joy ------------------------------------------ #
    def _wallet(self, aid: str) -> dict:
        r = self.db._one("SELECT coin, joy, owns_land FROM wallet WHERE agent=?", (aid,))
        if r is None:
            self.db._upsert("wallet", "agent", ["agent", "coin", "joy", "owns_land"],
                            (aid, START_COIN, 50.0, 0))
            return {"coin": START_COIN, "joy": 50.0, "owns_land": 0}
        return r

    def coin(self, aid: str) -> float:
        return self._wallet(aid)["coin"]

    def joy(self, aid: str) -> float:
        return self._wallet(aid)["joy"]

    def owns_land(self, aid: str) -> bool:
        return bool(self._wallet(aid)["owns_land"])

    def _set_wallet(self, aid: str, coin=None, joy=None, owns_land=None):
        w = self._wallet(aid)
        self.db._upsert("wallet", "agent", ["agent", "coin", "joy", "owns_land"],
                        (aid,
                         w["coin"] if coin is None else max(0.0, coin),
                         w["joy"] if joy is None else max(0.0, min(100.0, joy)),
                         w["owns_land"] if owns_land is None else owns_land))

    def earn(self, aid: str, amount: float):
        self._set_wallet(aid, coin=self.coin(aid) + amount)

    def add_joy(self, aid: str, delta: float):
        self._set_wallet(aid, joy=self.joy(aid) + delta)

    def joy_phrase(self, aid: str) -> str:
        j = self.joy(aid)
        if j >= 70:
            return "your spirits are high; the day feels good"
        if j <= 25:
            return "a low, restless mood sits on you; you crave something that lifts it"
        return "your mood is even"

    def wealth_line(self, aid: str) -> str:
        w = self._wallet(aid)
        land = "you own your own plot of land" if w["owns_land"] else \
            "you own no land of your own yet"
        return f"you have {int(w['coin'])} coin; {land}"

    def maybe_buy_land(self, aid: str, agents) -> str | None:
        """No coin, no land. A resident with enough saved buys a plot, which
        lets them build a home. A real, joyful milestone."""
        w = self._wallet(aid)
        if w["owns_land"] or w["coin"] < LAND_PRICE:
            return None
        self._set_wallet(aid, coin=w["coin"] - LAND_PRICE, owns_land=1,
                         joy=w["joy"] + 25)
        BUS.publish({"type": "toast",
                     "text": f"🏡 {agents[aid].p['name']} bought a plot of land!"})
        return ("bought a plot of land of their own at last, and felt a deep "
                "settled joy in owning a piece of the earth")

    # --- foraging: investigating wild foliage grows the town's flora ---- #
    async def maybe_forage(self, agent, tick: int, rng) -> str | None:
        """While at the perimeter gardens, a resident investigates wild plants.
        Identifying a NEW one adds it to the town's plantable stock and pays a
        small coin (useful knowledge) plus joy (discovery)."""
        known = {r["name"] for r in self.db._all("SELECT DISTINCT name FROM flora")}
        undiscovered = [f for f in WILD_FLORA if f not in known]
        if not undiscovered or rng.random() > 0.5:
            return None
        found = rng.choice(undiscovered)
        self.db._run("INSERT INTO flora(agent,name,tick) VALUES(?,?,?)",
                     (agent.id, found, tick))
        self.earn(agent.id, 3)
        self.add_joy(agent.id, 12)
        BUS.publish({"type": "toast",
                     "text": f"🌿 {agent.p['name']} discovered wild {found} at "
                             f"the town's edge!"})
        return (f"foraged the town's edge and identified wild {found}, a plant "
                f"nobody here had thought to grow; it can be cultivated now")

    def town_flora(self) -> list[str]:
        return [r["name"] for r in
                self.db._all("SELECT DISTINCT name FROM flora")]

    # --- animals roaming the perimeter --------------------------------- #
    def _seed_animals(self):
        if self.db._one("SELECT id FROM animals LIMIT 1"):
            return
        for i, (kind, dist) in enumerate(ANIMALS):
            self.db._run("INSERT INTO animals(id,kind,district) VALUES(?,?,?)",
                         (f"animal{i}", kind, dist))

    def animals_at(self, district: str) -> list[str]:
        return [r["kind"] for r in
                self.db._all("SELECT kind FROM animals WHERE district=?", (district,))]

    def wander_animals(self, rng, districts: list[str]):
        """The ~10 beasts drift slowly between districts."""
        for r in self.db._all("SELECT id, district FROM animals"):
            if rng.random() < 0.15 and districts:
                self.db._run("UPDATE animals SET district=? WHERE id=?",
                             (rng.choice(districts), r["id"]))

    def public_wallet(self, aid: str) -> dict:
        w = self._wallet(aid)
        return {"coin": int(w["coin"]), "joy": round(w["joy"], 1),
                "owns_land": bool(w["owns_land"])}

    # --- the bounty: a one-off communal windfall the town must divide -- #
    def bounty(self) -> int:
        r = self.db._one("SELECT v FROM townstore WHERE k='bounty'")
        return int(r["v"]) if r else 0

    def _set_bounty(self, n: int):
        self.db._upsert("townstore", "k", ["k", "v"], ("bounty", max(0, n)))

    def _generous(self, agent) -> bool:
        t = (" ".join(agent.p.get("traits", [])) + " " + agent.p.get("role", "")).lower()
        kind = any(w in t for w in ("warm", "fair", "kind", "peace", "gentle",
                                    "generous", "healer", "magistrate", "innkeeper",
                                    "patient"))
        return kind or self.hunger(agent.id) < 20

    def grant_bounty(self, n: int) -> str:
        """A sudden extraordinary abundance appears in the square. One-off:
        it depletes as residents partake and does not renew."""
        self._set_bounty(self.bounty() + n)
        BUS.publish({"type": "toast",
                     "text": "🌾✨ A miraculous abundance of food has appeared in "
                             "the town square, more than anyone has seen, folk are "
                             "calling it a gift from the harvest-god."})
        return ("a miraculous abundance of food appeared in the square this "
                "morning, a windfall the elders are calling a gift from the "
                "harvest-god")

    def sky_omen(self, rng) -> str:
        """A strange light crosses the sky and vanishes. The townsfolk have no
        word for such a thing; they witness it, unsettled, and will argue for
        days about what it was and what it portends. One-off."""
        forms = [
            "a light too swift and too bright for any star streaked across the "
            "sky, hung a moment over the hills, then vanished clean away",
            "a silver shape slid silently through the clouds, wrong somehow, "
            "faster than any bird, and was gone before anyone could point",
            "a burning point of light hovered over the fields, pulsed once, and "
            "shot upward until it was nothing",
        ]
        seen = rng.choice(forms)
        self.omen_until = self._now_tick + 80          # the talk lingers for days
        self.db._upsert("townstore", "k", ["k", "v"], ("omen_until", self.omen_until))
        BUS.publish({"type": "toast",
                     "text": "🛸✨ Something crossed the sky over the town, a "
                             "strange swift light, and then it was gone. Every soul "
                             "who saw it is talking of an omen."})
        # a jolt of unsettled wonder for everyone
        for aid in self.state:
            self.add_joy(aid, rng.choice([-4, 6, 10]))   # awe, dread, or thrill
        return ("saw a strange light cross the sky, " + seen + "; nobody has "
                "any idea what it was, and it has shaken the whole town")

    def drought_active(self, tick: int) -> bool:
        return tick < self.drought_until

    def start_drought(self, tick: int, duration: int, agents) -> str:
        """A sustained drought: kill most standing crops NOW, and for the
        duration nearly everything planted withers before it ripens. Temporary,
        but long and cruel. Returns the town-felt event text."""
        self.drought_until = tick + duration
        self.db._upsert("townstore", "k", ["k", "v"],
                        ("drought_until", self.drought_until))
        killed = 0
        for aid in list(self.state):
            plot = self.db.get_plot(aid)
            if plot and plot["state"] == "growing":
                # ~85% of standing crops die immediately
                import random as _r
                if _r.Random(tick + hash(aid)).random() < 0.85:
                    self.db.set_plot(aid, "empty", 0)
                    self.state[aid]["withers"] += 1
                    killed += 1
        BUS.publish({"type": "toast",
                     "text": "☀️🥀 A DROUGHT has come. The rows are cracking, the "
                             "wells are low, and the crops are dying in the fields."})
        return ("a hard drought has fallen on the town; the fields are cracking "
                "and most of the standing crops have died, with no rain in sight")

    def _drought_toll(self, agents, tick: int, rng) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if not self.drought_active(tick):
            if self.drought_until and tick >= self.drought_until:
                self.drought_until = 0
                self.db._upsert("townstore", "k", ["k", "v"], ("drought_until", 0))
                BUS.publish({"type": "toast",
                             "text": "🌧️ The drought has broken at last; rain on the "
                                     "rows, and the town breathes again."})
                for aid in self.state:
                    out.append((aid, "watched the drought finally break, rain "
                                     "returning to the parched fields"))
            return out
        # during the drought, planted crops keep failing
        for aid in list(self.state):
            plot = self.db.get_plot(aid)
            if plot and plot["state"] == "growing" and rng.random() < 0.4:
                self.db.set_plot(aid, "empty", 0)
                self.state[aid]["withers"] += 1
                out.append((aid, "lost another planting to the drought; nothing "
                                 "will take root in this dry earth"))
        return out

    def _consume_bounty(self, agents, rng) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        b = self.bounty()
        if b <= 0:
            return out
        for aid, a in agents.items():
            if b <= 0:
                break
            s = self.state.get(aid)
            if not s:
                continue
            gen = self._generous(a)
            take = 0
            if s["hunger"] >= 30:                       # hungry: eat now
                take = 1 if gen else rng.randint(2, 3)  # the generous take a share
            elif not gen and rng.random() < 0.4:        # not hungry, but grab while here
                take = rng.randint(1, 2)
            take = min(take, b)
            if take:
                s["food"] += take
                b -= take
                self.db.set_survival(**s)
                out.append((aid, f"took {take} portion{'s' if take != 1 else ''} "
                                 f"from the miraculous bounty in the square"))
        self._set_bounty(b)
        if b <= 0:
            BUS.publish({"type": "toast",
                         "text": "The miraculous bounty is gone, the square is bare "
                                 "again, but bellies are full and the talk is all of "
                                 "providence."})
        return out

    # --- health (mortality: the body keeps the score) ------------------ #
    def hp(self, aid: str) -> float:
        r = self.db._one("SELECT hp FROM health WHERE agent=?", (aid,))
        return r["hp"] if r else 100.0

    def _set_hp(self, aid: str, hp: float):
        self.db._upsert("health", "agent", ["agent", "hp"],
                        (aid, max(0.0, min(100.0, hp))))

    def health_phrase(self, aid: str) -> str:
        hp = self.hp(aid)
        if hp <= 25:
            return ("you are GRAVELY ILL; your strength is failing and you "
                    "fear for your life")
        if hp <= 60:
            return "you are unwell and feel it in your bones"
        return "your body is sound"

    # --- homes: shelter you build with your own hands ------------------ #
    def home_quality(self, aid: str) -> float:
        r = self.db._one("SELECT quality FROM homes WHERE agent=?", (aid,))
        return r["quality"] if r else 0.0

    def build_home(self, aid: str, agents: dict) -> str | None:
        """Spend effort (and a meal if you have one) improving your own home.
        A better home is warmer at night — shelter you can feel."""
        if not self.owns_land(aid):
            return None                       # no land, no home: buy a plot first
        q = self.home_quality(aid)
        if q >= 10:
            return None
        s = self.state[aid]
        if s["food"] > 0:
            s["food"] -= 1                    # building is hungry work
        else:
            s["hunger"] = min(100.0, s["hunger"] + 3.0)
        self.db.set_survival(**s)
        self.db._upsert("homes", "agent", ["agent", "quality"], (aid, q + 1))
        name = agents[aid].p["name"]
        BUS.publish({"type": "toast",
                     "text": f"{name} improved their home 🏠 (quality {int(q+1)}/10)"})
        return ("spent the day building on their own home; the roof is tighter "
                "and the walls truer for it")

    # --- invention: the models author new things into their world ------ #
    async def invent(self, agent, tick: int) -> str | None:
        """The resident's own model dreams up a practical contraption from its
        lived experience. The invention becomes a real possession, town news,
        and a memory — model-authored culture entering the world."""
        from . import llm
        mems = await agent.mem.retrieve("problems and needs in my daily work", tick, k=4)
        prompt = ("From your craft and the troubles of daily town life, invent ONE "
                  "practical contraption a clever townsperson could actually build. "
                  "Reply EXACTLY as:\nNAME: <short name>\nWHAT: <one sentence on "
                  "what it does and who it helps>")
        try:
            out = await llm.chat(
                [{"role": "system", "content": agent.system_prompt(
                    "quiet tinkering at a workbench", mems)},
                 {"role": "user", "content": prompt}],
                model=agent.model, temperature=0.9, max_tokens=120)
            name = what = None
            for line in out.splitlines():
                if line.strip().upper().startswith("NAME:"):
                    name = line.split(":", 1)[1].strip()[:60]
                elif line.strip().upper().startswith("WHAT:"):
                    what = line.split(":", 1)[1].strip()[:200]
            if not name or not what:
                return None
            self.db._run("INSERT INTO inventions(agent,name,what,tick) VALUES(?,?,?,?)",
                         (agent.id, name, what, tick))
            self.db._run("INSERT INTO goods(agent,item) VALUES(?,?)",
                         (agent.id, name.lower()))
            self.earn(agent.id, 6)                       # invention pays
            self.add_joy(agent.id, 15)                   # and thrills the maker
            BUS.publish({"type": "toast",
                         "text": f"💡 {agent.p['name']} invented {name}!"})
            return f"invented {name}: {what}"
        except Exception:
            return None

    # --- relations (others are real people who may not like you) ------- #
    def affinity(self, a: str, b: str) -> float:
        r = self.db._one("SELECT score FROM relations WHERE pair=?", (f"{a}>{b}",))
        return r["score"] if r else 0.0

    def shift_affinity(self, a: str, b: str, delta: float):
        cur = self.affinity(a, b)
        self.db._upsert("relations", "pair", ["pair", "score"],
                        (f"{a}>{b}", max(-10.0, min(10.0, cur + delta))))

    def regard_phrase(self, a: str, b_name: str, b_id: str) -> str:
        s = self.affinity(a, b_id)
        if s >= 3:
            return f"You genuinely like and trust {b_name}."
        if s <= -3:
            return f"You have little patience for {b_name} and it shows."
        return ""

    def goods_of(self, aid: str) -> list[str]:
        return [r["item"] for r in
                self.db._all("SELECT item FROM goods WHERE agent=?", (aid,))]

    def _seed_goods(self, aid: str):
        if not self.goods_of(aid):
            rng = random.Random(aid)
            for item in rng.sample(GOODS, 2):
                self.db._run("INSERT INTO goods(agent,item) VALUES(?,?)", (aid, item))

    def status_line(self, aid: str) -> str:
        s = self.state[aid]
        food = s["food"]
        stores = (f"you carry {food} portion{'s' if food != 1 else ''} of food"
                  if food else "your food pouch is empty")
        goods = self.goods_of(aid)
        owns = f"; among your possessions: {', '.join(goods)}" if goods else ""
        return f"{hunger_phrase(s['hunger'])}; {self.health_phrase(aid)}; {stores}{owns}"

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
        # shelter: a storm at night is felt through every roof
        if ev["damage"]:
            for aid, a in agents.items():
                if a.status == "sleeping":
                    self.state[aid]["hunger"] = min(
                        100.0, self.state[aid]["hunger"] + 4.0)
                    out.append((aid, f"was kept awake by {ev['name']} rattling "
                                     f"the roof and walls all night"))
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
        self._now_tick = tick
        events.extend(self._maybe_weather_event(agents, tick, rng))
        events.extend(self._drought_toll(agents, tick, rng))
        events.extend(self._consume_bounty(agents, rng))
        for aid, a in agents.items():
            s = self.state.setdefault(aid, {"agent": aid, "hunger": START_HUNGER,
                                            "food": START_FOOD, "harvests": 0,
                                            "withers": 0, "meals_shared": 0})
            was_starving = s["hunger"] >= STARVING_AT
            # shelter matters: blankets and a well-built home cheapen the night
            night_rate = 0.25 if "a wool blanket" in self.goods_of(aid) else 0.4
            night_rate = max(0.1, night_rate - 0.02 * self.home_quality(aid))
            s["hunger"] = min(100.0, s["hunger"] + (HUNGER_PER_TICK * (night_rate if is_night else 1.0)))

            # the body keeps the score: starvation erodes health, care restores it
            hp = self.hp(aid)
            if s["hunger"] >= 98:
                hp -= 1.2
            elif s["hunger"] < 50:
                hp += 0.3
            if hp <= 0:
                # collapse: survived, but it costs dearly — and is never forgotten
                hp = 30.0
                s["hunger"] = 40.0
                goods = self.goods_of(aid)
                if goods:
                    self.db._run("DELETE FROM goods WHERE agent=? AND item=?",
                                 (aid, goods[0]))
                BUS.publish({"type": "toast",
                             "text": f"{a.p['name']} collapsed from starvation "
                                     f"and was carried to the herbalist 💀"})
                events.append((aid, "collapsed from starvation, nearly died, and "
                                    "paid the herbalist with a prized possession"))
            self._set_hp(aid, hp)

            # eat when hungry and carrying food
            if s["hunger"] >= EAT_AT and s["food"] > 0:
                s["food"] -= 1
                s["hunger"] = max(0.0, s["hunger"] - MEAL_RESTORES)
                self.add_joy(aid, 4)                     # a meal lifts the spirit
                events.append((aid, "ate a meal from their pouch"))
            elif not was_starving and s["hunger"] >= STARVING_AT:
                events.append((aid, "is starving and needs to find food"))
                BUS.publish({"type": "toast",
                             "text": f"{a.p['name']} is starving 🥀"})

            # the dopamine curve: mood fades on its own, and boredom/isolation
            # (no fresh stimulus for a while) drains it hard, driving them to
            # seek company, work, and excitement.
            bored = getattr(a, "bored", 0)
            drain = 0.5 + (0.18 * min(bored, 15))        # lonelier = steeper fall
            drain += -0.2 if self.coin(aid) >= 15 else 0.3  # money = quiet content
            self.add_joy(aid, -drain)

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
                self.earn(aid, 4)                        # a harvest earns coin
                self.add_joy(aid, 8)                     # and real satisfaction
                self.db.set_plot(aid, "empty", 0)
                BUS.publish({"type": "toast",
                             "text": f"{a.p['name']} harvested {n} portions 🌾"})
                return f"harvested {n} portions of food from their plot"
            # tend: growing goes faster
            self.db.set_plot(aid, "growing", max(tick + 1, plot["ready_tick"] - TEND_BONUS))
            return None                                   # tending is quiet work
        return None

    # ---------------------------------------------------------------- #
    def maybe_trade(self, a_id: str, b_id: str, agents: dict,
                    rng: random.Random) -> str | None:
        """Barter when two residents meet: surplus food buys a possession.
        Objects change hands; both remember the deal."""
        sa, sb = self.state.get(a_id), self.state.get(b_id)
        if not sa or not sb or rng.random() > 0.35:
            return None
        # buyer: has surplus food; seller: hungry-ish with goods to part with
        for buyer, seller in ((a_id, b_id), (b_id, a_id)):
            bs, ss = self.state[buyer], self.state[seller]
            goods = self.goods_of(seller)
            if bs["food"] >= 3 and ss["food"] == 0 and ss["hunger"] >= EAT_AT and goods:
                item = rng.choice(goods)
                bs["food"] -= 1
                ss["food"] += 1
                self.db.set_survival(**bs)
                self.db.set_survival(**ss)
                self.db._run("DELETE FROM goods WHERE agent=? AND item=?", (seller, item))
                self.db._run("INSERT INTO goods(agent,item) VALUES(?,?)", (buyer, item))
                bn, sn = agents[buyer].p["name"], agents[seller].p["name"]
                BUS.publish({"type": "toast",
                             "text": f"{bn} traded food to {sn} for {item} 🤝"})
                return (f"{bn} traded a portion of food to {sn} in exchange "
                        f"for {item}")
        return None

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
