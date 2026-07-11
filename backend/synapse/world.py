"""World map: districts, road graph, frontier gates, and shortest-path waypoint
routing that the 3D frontend animates avatars along. The map is MUTABLE: the
worldgen module grows it while the sim runs, and every mutation is persisted to
run/world_evolved.json so the town keeps its shape across restarts."""
from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass

from .config import CONFIG

EVOLVED_FILE = CONFIG.db_file.parent / "world_evolved.json"


@dataclass
class District:
    id: str
    name: str
    kind: str
    pos: dict            # {"x": float, "z": float}
    color: str
    activity: str
    signal: str
    archetype: str = "seed"
    level: int = 1
    xp: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class WorldMap:
    def __init__(self, spec: dict):
        self.name: str = spec["name"]
        self.size: dict = spec["size"]
        self.districts: dict[str, District] = {}
        for d in spec["districts"]:
            self.districts[d["id"]] = District(
                d["id"], d["name"], d["kind"], d["pos"], d["color"],
                d["activity"], d["signal"], d.get("archetype", "seed"),
                d.get("level", 1), d.get("xp", 0))
        self.roads: list[list[str]] = [list(r) for r in spec["roads"]]
        self.frontiers: list[dict] = list(spec.get("frontiers", []))
        self._adj: dict[str, set[str]] = {d: set() for d in self.districts}
        for a, b in self.roads:
            self._adj[a].add(b)
            self._adj[b].add(a)
        if not self.frontiers:
            from . import worldgen
            self.frontiers = worldgen.seed_frontiers(
                self, random.Random(CONFIG.seed))

    # ------------------------------------------------------------------ #
    def add_district(self, district: dict, road: list[str],
                     frontiers: list[dict], opened: str) -> None:
        d = District(district["id"], district["name"], district["kind"],
                     district["pos"], district["color"], district["activity"],
                     district["signal"], district.get("archetype", "seed"),
                     district.get("level", 1), district.get("xp", 0))
        self.districts[d.id] = d
        self.roads.append(list(road))
        self._adj.setdefault(d.id, set())
        self._adj[road[0]].add(road[1])
        self._adj[road[1]].add(road[0])
        self.frontiers = [f for f in self.frontiers if f["id"] != opened]
        self.frontiers.extend(frontiers)
        self.save()

    def frontier_districts(self) -> set[str]:
        return {f["from"] for f in self.frontiers}

    def grant_xp(self, district_id: str, amount: int) -> int | None:
        """Add xp; returns the new level if the district levelled up."""
        from . import worldgen
        d = self.districts[district_id]
        d.xp += amount
        lvl = worldgen.level_for(d.xp)
        if lvl > d.level:
            d.level = lvl
            self.save()
            return lvl
        return None

    def save(self) -> None:
        EVOLVED_FILE.write_text(json.dumps(self.to_dict(), indent=1),
                                encoding="utf-8")

    # ------------------------------------------------------------------ #
    def route(self, start: str, goal: str) -> list[str]:
        """BFS shortest path of district ids (inclusive of endpoints)."""
        if start == goal:
            return [goal]
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == goal:
                break
            for nxt in self._adj[cur]:
                if nxt not in prev:
                    prev[nxt] = cur
                    q.append(nxt)
        if goal not in prev:
            return [goal]
        path, cur = [], goal
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        return list(reversed(path))

    def waypoints(self, path: list[str]) -> list[dict]:
        return [self.districts[d].pos for d in path]

    def to_dict(self) -> dict:
        return {
            "name": self.name, "size": self.size, "roads": self.roads,
            "frontiers": self.frontiers,
            "districts": [d.to_dict() for d in self.districts.values()],
        }


def load_world() -> WorldMap:
    if EVOLVED_FILE.exists():
        try:
            return WorldMap(json.loads(EVOLVED_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            pass                                     # fall back to the seed map
    return WorldMap(json.loads(CONFIG.world_file.read_text(encoding="utf-8")))


def load_personas() -> list[dict]:
    return json.loads(CONFIG.personas_file.read_text(encoding="utf-8"))["agents"]
