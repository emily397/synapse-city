"""Procedural world growth. The town expands the same way its residents do:
by learning. Districts that agents actually use accumulate XP and level up;
frontier gates ring the known world, and when a curious agent opens one the
generator births a new district whose *kind* is biased by what the town has
been doing lately (lots of debate -> more debate ground, lots of teaching ->
another hall). Every mutation is persisted so the world survives restarts.
"""
from __future__ import annotations

import math
import random

# Visual archetype -> training-signal kind. `kind` drives conversations and
# harvest exactly like the seed districts; `archetype` drives the 3D look.
ARCHETYPES: list[dict] = [
    {"archetype": "observatory", "kind": "reasoning", "color": "#4fb6ff",
     "activity": "stargazing hypotheses and probing Q&A", "signal": "sft_reasoning"},
    {"archetype": "beacon", "kind": "reasoning", "color": "#6ec6ff",
     "activity": "long-sight reasoning over hard questions", "signal": "sft_reasoning"},
    {"archetype": "foundry", "kind": "building", "color": "#ff9a52",
     "activity": "forging concrete build/solve tasks", "signal": "sft_procedural"},
    {"archetype": "mill", "kind": "building", "color": "#ffb36b",
     "activity": "iterating on working mechanisms", "signal": "sft_procedural"},
    {"archetype": "athenaeum", "kind": "teaching", "color": "#43df85",
     "activity": "patient explanation among the shelves", "signal": "distillation"},
    {"archetype": "archive", "kind": "teaching", "color": "#5fe89d",
     "activity": "recovering and re-teaching old insight", "signal": "distillation"},
    {"archetype": "colosseum", "kind": "debate", "color": "#ff5d8f",
     "activity": "formal argument before a judge", "signal": "dpo_preference"},
    {"archetype": "gallery", "kind": "creative", "color": "#c07bff",
     "activity": "divergent riffs and strange angles", "signal": "diversity"},
    {"archetype": "greenhouse", "kind": "creative", "color": "#d59aff",
     "activity": "growing ideas under glass", "signal": "diversity"},
    {"archetype": "bazaar", "kind": "social", "color": "#ffd166",
     "activity": "trading stories stall to stall", "signal": "none"},
    {"archetype": "harbor", "kind": "social", "color": "#ffe08a",
     "activity": "idle talk at the water's edge", "signal": "none"},
    {"archetype": "shrine", "kind": "rest", "color": "#9aa7bd",
     "activity": "quiet reflection and memory-keeping", "signal": "reflection"},
]

_NAME_A = ["Vesper", "Ember", "Cobalt", "Meridian", "Larkspur", "Quill",
           "Halcyon", "Juniper", "Sable", "Aurora", "Fable", "Onyx",
           "Marigold", "Cinder", "Willow", "Zephyr", "Isolde", "Bramble",
           "Lumen", "Saffron", "Tidal", "Hollow", "Gilded", "Whisper"]
_NAME_B = {"observatory": "Observatory", "beacon": "Beacon", "foundry": "Foundry",
           "mill": "Mill", "athenaeum": "Athenaeum", "archive": "Archive",
           "colosseum": "Grounds", "gallery": "Gallery", "greenhouse": "Greenhouse",
           "bazaar": "Bazaar", "harbor": "Harbor", "shrine": "Shrine"}

_GATE_NAMES = ["Ember Gate", "Fog Door", "Vesper Arch", "Hollow Door",
               "Starward Gate", "Quiet Door", "Bramble Gate", "Tidal Arch",
               "Cinder Door", "Lumen Gate", "Whisper Arch", "Gilded Door"]

MIN_DISTRICT_GAP = 17.0     # world units between district centres
STEP_OUT = 26.0             # how far past its parent a new district lands


def seed_frontiers(world, rng: random.Random) -> list[dict]:
    """Ring the seed town with 3 dream-gates on outward-facing districts."""
    frontiers = []
    outer = sorted(world.districts.values(),
                   key=lambda d: -(d.pos["x"] ** 2 + d.pos["z"] ** 2))[:3]
    for i, d in enumerate(outer):
        ang = math.atan2(d.pos["z"], d.pos["x"]) + rng.uniform(-0.35, 0.35)
        frontiers.append(_frontier(d.id, d.pos, ang, rng, i))
    return frontiers


def _frontier(from_id: str, from_pos: dict, ang: float,
              rng: random.Random, salt: int) -> dict:
    return {
        "id": f"gate_{from_id}_{salt}_{rng.randrange(9999)}",
        "from": from_id,
        "name": rng.choice(_GATE_NAMES),
        "dir": round(ang, 3),
        "pos": {"x": round(from_pos["x"] + math.cos(ang) * 12.5, 1),
                "z": round(from_pos["z"] + math.sin(ang) * 12.5, 1)},
    }


def _pick_archetype(activity_stats: dict[str, int], existing_kinds: list[str],
                    rng: random.Random) -> dict:
    """The world learns: weight new-district kinds by what agents do most,
    damped by how much of that kind already exists."""
    supply: dict[str, int] = {}
    for k in existing_kinds:
        supply[k] = supply.get(k, 0) + 1
    weights = []
    for arch in ARCHETYPES:
        demand = 1.0 + activity_stats.get(arch["kind"], 0) * 0.6
        w = demand / (1.0 + supply.get(arch["kind"], 0) * 0.5)
        weights.append(w)
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for arch, w in zip(ARCHETYPES, weights):
        acc += w
        if r <= acc:
            return arch
    return ARCHETYPES[-1]


def generate_district(world, frontier: dict, activity_stats: dict[str, int],
                      rng: random.Random) -> dict | None:
    """Birth a district beyond `frontier`. Returns an expansion bundle or None
    if no clear land exists in that direction."""
    parent = world.districts[frontier["from"]]
    base_ang = frontier["dir"]
    pos = None
    for attempt in range(10):
        ang = base_ang + rng.uniform(-0.55, 0.55) * (1 + attempt * 0.25)
        dist = STEP_OUT + rng.uniform(-3, 7) + attempt * 2.5
        cand = {"x": round(parent.pos["x"] + math.cos(ang) * dist, 1),
                "z": round(parent.pos["z"] + math.sin(ang) * dist, 1)}
        if all(math.hypot(cand["x"] - d.pos["x"], cand["z"] - d.pos["z"])
               >= MIN_DISTRICT_GAP for d in world.districts.values()):
            pos, ang_used = cand, ang
            break
    if pos is None:
        return None

    arch = _pick_archetype(activity_stats,
                           [d.kind for d in world.districts.values()], rng)
    prefix = rng.choice([p for p in _NAME_A
                         if not any(p in d.name for d in world.districts.values())]
                        or _NAME_A)
    name = f"The {prefix} {_NAME_B[arch['archetype']]}"
    did = f"{prefix.lower()}_{arch['archetype']}"
    n = 2
    while did in world.districts:
        did = f"{prefix.lower()}_{arch['archetype']}{n}"
        n += 1

    district = {
        "id": did, "name": name, "kind": arch["kind"], "pos": pos,
        "color": arch["color"], "activity": arch["activity"],
        "signal": arch["signal"], "archetype": arch["archetype"],
        "level": 1, "xp": 0,
    }

    # The world keeps growing: the new district opens 1-2 gates of its own,
    # facing away from town.
    out_ang = math.atan2(pos["z"], pos["x"])
    new_frontiers = [_frontier(did, pos, out_ang + rng.uniform(-0.5, 0.5), rng, 0)]
    if rng.random() < 0.55:
        new_frontiers.append(_frontier(did, pos,
                                       out_ang + rng.choice([-1, 1]) * rng.uniform(0.9, 1.6),
                                       rng, 1))

    return {"district": district, "road": [frontier["from"], did],
            "frontiers": new_frontiers, "opened": frontier["id"]}


LEVEL_XP = [0, 14, 40, 90]      # xp thresholds for levels 1..4


def level_for(xp: int) -> int:
    lvl = 1
    for i, need in enumerate(LEVEL_XP):
        if xp >= need:
            lvl = i + 1
    return min(lvl, 4)
