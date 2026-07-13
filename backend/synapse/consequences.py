"""Causation & consequences: actions ripple through shared resources in logical,
predictable DOMINOES. One heavy harvest tires the soil; tired soil thins the
crop; a thin crop drives the price up; costly food deepens hunger; hunger breeds
unrest; unrest frays friendships. Rain and rest push the other way. Every link is
a REAL effect (on food, health, mood, affinity) AND a remembered cause->effect
written to the residents who feel it — so, over time, they can learn how their
world actually works.

Shared environment lives in the `townstore` (k/v), so it persists across restarts.
The chain unfolds over successive days: crossing one threshold today sets up the
next domino tomorrow.
"""
from __future__ import annotations

from .bus import BUS

# env keys and their starting values (0..1 unless noted)
_DEFAULTS = {
    "env_soil": 0.80,      # garden fertility — depleted by harvesting, restored by rain/rest
    "env_water": 0.80,     # depleted by farming/drought, restored by rain
    "env_forest": 0.90,    # wild flora/wood — depleted by foraging/building, regrows slowly
    "env_price": 5.0,      # price of food in coin — supply & demand (not 0..1)
    "env_unrest": 0.10,    # social tension — scarcity raises it, plenty lowers it
}


class Consequences:
    def __init__(self, db):
        self.db = db
        for k, v in _DEFAULTS.items():
            if db._one("SELECT v FROM townstore WHERE k=?", (k,)) is None:
                db._upsert("townstore", "k", ["k", "v"], (k, v))

    def _get(self, k: str) -> float:
        r = self.db._one("SELECT v FROM townstore WHERE k=?", (k,))
        return r["v"] if r else _DEFAULTS.get(k, 0.0)

    def _set(self, k: str, v: float):
        self.db._upsert("townstore", "k", ["k", "v"], (k, v))

    def state(self) -> dict:
        return {k: round(self._get(k), 3) for k in _DEFAULTS}

    # ------------------------------------------------------------------ #
    def settle(self, survival, agents: dict, day: int, rng) -> list[tuple[str, str]]:
        """One day of cause-and-effect. Returns (agent_id, memory) pairs so the
        sim can persist them — residents remember what caused what."""
        mem: list[tuple[str, str]] = []
        ids = list(agents)
        if not ids:
            return mem

        soil, water, forest = self._get("env_soil"), self._get("env_water"), self._get("env_forest")
        price, unrest = self._get("env_price"), self._get("env_unrest")

        # --- 1. pressure from the town's own actions (attributed to the busiest) ---
        harv = {a: survival.state.get(a, {}).get("harvests", 0) for a in ids}
        last = self._get("env_last_harv_total")
        total = sum(harv.values())
        delta = max(0.0, total - last)            # harvests since yesterday
        self._set("env_last_harv_total", total)
        worker = max(ids, key=lambda a: harv.get(a, 0)) if total else None

        weather = survival.current_weather(day).lower()
        rainy = any(w in weather for w in ("rain", "storm", "wet", "shower"))
        dry = any(w in weather for w in ("drought", "dry", "heat", "sun-bak"))

        # coupled dynamics (deterministic, predictable)
        soil = _clamp(soil - 0.03 * min(delta, 6) + (0.10 if rainy else 0.02) - (0.05 if dry else 0))
        water = _clamp(water - 0.04 * min(delta, 6) + (0.22 if rainy else 0.0) - (0.10 if dry else 0.03))
        forest = _clamp(forest - 0.015 * min(delta, 6) + 0.05)   # slow regrowth

        # --- 2. the domino chain: each crossed threshold is a real effect + memory ---
        # A. tired soil / no water -> the crop fails -> food scarce, price climbs
        if soil < 0.35 or water < 0.3:
            price = min(20.0, price + 1.8)
            cause = (f"{agents[worker].p['name']}'s heavy harvesting" if worker
                     else "the long dry spell")
            for a in ids:
                s = survival.state.get(a)
                if s and s.get("food", 0) > 0 and rng.random() < 0.6:
                    s["food"] = max(0, s["food"] - 1)      # crops came up short
            BUS.publish({"type": "toast", "text": "The soil is spent — harvests came "
                         "up thin and food is scarcer. Prices are climbing."})
            for a in rng.sample(ids, min(4, len(ids))):
                mem.append((a, f"Because {cause} tired the gardens, the soil is spent; "
                               f"crops are thin and food costs more now."))
        # B. dear food -> the poor go hungry -> unrest rises
        if price > 8.0:
            for a in ids:
                if survival.coin(a) < price and rng.random() < 0.5:
                    s = survival.state.get(a)
                    if s:
                        s["hunger"] = min(100.0, s.get("hunger", 0) + 6)   # can't afford to eat
            unrest = _clamp(unrest + 0.16)
            BUS.publish({"type": "toast", "text": f"Food is dear ({price:.0f} coin). "
                         "Those without coin go hungry, and the mood sours."})
            for a in rng.sample(ids, min(3, len(ids))):
                mem.append((a, "Food grew too dear to afford; going hungry, I feel the "
                               "town's temper fraying."))
        # C. high unrest -> friendships fray, someone withdraws
        if unrest > 0.5 and len(ids) >= 2:
            for _ in range(min(3, len(ids) // 2)):
                x, y = rng.sample(ids, 2)
                survival.shift_affinity(x, y, -1.2)
                survival.shift_affinity(y, x, -1.2)
                survival.add_joy(x, -3)
            BUS.publish({"type": "toast", "text": "Scarcity frays tempers — old friends "
                         "quarrel and trust thins across the town."})
            for a in rng.sample(ids, min(3, len(ids))):
                mem.append((a, "The hard times set neighbours against each other; a "
                               "quarrel today that easier days would never have caused."))
            unrest = _clamp(unrest - 0.1)     # the tension partly discharges
        # D. plenty -> the other way: cheap food, full bellies, rising spirits
        if soil > 0.82 and price < 4.5 and unrest < 0.25:
            price = max(2.0, price - 0.8)
            for a in ids:
                s = survival.state.get(a)
                if s:
                    s["food"] = min(9, s.get("food", 0) + 1)     # a good season
                survival.add_joy(a, 2)
            unrest = _clamp(unrest - 0.08)
            BUS.publish({"type": "toast", "text": "A bountiful season — stores are full, "
                         "food is cheap, and spirits lift across the town."})
            for a in rng.sample(ids, min(3, len(ids))):
                mem.append((a, "The gardens gave plenty this season; full stores and "
                               "cheap food have lifted everyone's mood."))
        # E. stripped forest -> foraging fails, the wild empties
        if forest < 0.3:
            BUS.publish({"type": "toast", "text": "The woods are over-picked — foraging "
                         "turns up little and the animals have moved on."})
            for a in rng.sample(ids, min(2, len(ids))):
                mem.append((a, "We stripped the woods bare; there's little left to "
                               "forage and the creatures have gone."))
            forest = _clamp(forest + 0.03)

        # price drifts back toward normal as supply recovers
        price += (5.0 - price) * 0.10
        unrest = _clamp(unrest - 0.03)

        for k, v in (("env_soil", soil), ("env_water", water), ("env_forest", forest),
                     ("env_price", price), ("env_unrest", unrest)):
            self._set(k, v)
        BUS.publish({"type": "env", **self.state()})
        return mem


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
