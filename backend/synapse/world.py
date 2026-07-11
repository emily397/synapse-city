"""World map: districts, road graph, and shortest-path waypoint routing that the
3D frontend animates avatars along."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

from .config import CONFIG


@dataclass
class District:
    id: str
    name: str
    kind: str
    pos: dict            # {"x": float, "z": float}
    color: str
    activity: str
    signal: str


class WorldMap:
    def __init__(self, spec: dict):
        self.name: str = spec["name"]
        self.size: dict = spec["size"]
        self.districts: dict[str, District] = {
            d["id"]: District(d["id"], d["name"], d["kind"], d["pos"],
                              d["color"], d["activity"], d["signal"])
            for d in spec["districts"]
        }
        self.roads: list[list[str]] = spec["roads"]
        self._adj: dict[str, set[str]] = {d: set() for d in self.districts}
        for a, b in self.roads:
            self._adj[a].add(b)
            self._adj[b].add(a)

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
            "districts": [d.__dict__ for d in self.districts.values()],
        }


def load_world() -> WorldMap:
    return WorldMap(json.loads(CONFIG.world_file.read_text(encoding="utf-8")))


def load_personas() -> list[dict]:
    return json.loads(CONFIG.personas_file.read_text(encoding="utf-8"))["agents"]
