"""Agent runtime: persona + physical state + prompt construction. Cognition lives
in memory.py; conversation orchestration in interactions.py."""
from __future__ import annotations

from .config import CONFIG
from .memory import MemoryStream
from .world import WorldMap
from .db import DB


class Agent:
    def __init__(self, persona: dict, world: WorldMap, db: DB):
        self.p = persona
        self.id = persona["id"]
        # Each resident can run its OWN model; empty falls back to the town default.
        self.model = persona.get("model") or CONFIG.chat_model
        self.mem = MemoryStream(self.id, db)
        self.district = persona["home"]
        self.pos = dict(world.districts[self.district].pos)
        self.status = "idle"                 # idle | traveling | interacting | sleeping
        self.path: list[str] = []            # remaining district ids to traverse
        self.partner: str | None = None
        self.cooldown = 0                    # ticks before it will seek a new interaction

    def system_prompt(self, district_activity: str, memories: list[str]) -> str:
        p = self.p
        mem = ("\nWhat you remember that's relevant:\n- " + "\n- ".join(memories)
               if memories else "")
        return (
            f"You are {p['name']}, the {p['role']} of Synapse City. {p['voice']}. "
            f"Your traits: {', '.join(p['traits'])}. You care about: {p['goal']}. "
            f"Right now you are in a place for {district_activity}. "
            f"Speak in character, 1-3 sentences, substantive, no stage directions.{mem}"
        )

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.p["name"], "role": self.p["role"],
            "emoji": self.p.get("emoji", "🤖"), "color": self.p["color"],
            "district": self.district, "pos": self.pos, "status": self.status,
            "partner": self.partner,
            "model": self.model,
            "avatar": self.p.get("avatar", {"body": "capsule", "hat": "none"}),
        }
