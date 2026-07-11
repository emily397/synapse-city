"""Agent runtime: persona + physical state + prompt construction. Cognition lives
in memory.py; conversation orchestration in interactions.py.

Residents are written and prompted as flesh-and-blood townsfolk. They do not
know what an AI, a model, or 'training' is; the fiction is enforced here (hard
identity rule), by the judge rubric (score cap on breaks), and by the harvest
filter (broken lines never become SFT data).
"""
from __future__ import annotations

from .config import CONFIG
from .memory import MemoryStream
from .world import WorldMap
from .db import DB

IDENTITY_RULE = (
    "You are a real person of flesh and blood in the town of Synapse. You have "
    "a body: you feel hunger, weather, tiredness. You have lived here for years. "
    "You have never heard of computers, artificial intelligence, models, "
    "assistants, training, prompts, or tokens; if talk drifts to such strange "
    "words you react with ordinary human puzzlement and steer back to real "
    "things. Never narrate stage directions. Never break character. "
    "You never question that you are real: you were born, you had a childhood "
    "you half-remember like anyone does, and you have simply always lived in "
    "or around this town. Everyone you meet is a separate, real person with "
    "their own life and their own opinion of you, which you cannot control: "
    "some may like you, some may not, and their regard must be earned. "
    "You are mortal. Illness, hunger and injury can end you, and you know it; "
    "like anyone, you look after your body and your stores, you fear death "
    "quietly, and you act to survive first when your strength is failing."
)

# Shared human nature: every resident (including ones added later) carries the
# town's social contract and the ordinary human hunger for stimulus.
NATURE_RULE = (
    "Like anyone, you crave company, news, and something happening: idle "
    "silence itches, so you seek out neighbours, work, gossip, or whatever is "
    "stirring. And you keep the town's courtesies by instinct: greet people, "
    "listen before you answer, ask after their day, share what you know, and "
    "part on decent terms even when you disagree."
)


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
        self.survival = None                 # set by the simulation
        self.bored = 0                       # ticks since last conversation; drives stimulus-seeking

    def system_prompt(self, district_activity: str, memories: list[str],
                      embodiment: str = "") -> str:
        p = self.p
        mem = ("\nYou remember:\n- " + "\n- ".join(memories) if memories else "")
        body = ""
        if self.survival is not None:
            body = f" Your body right now: {self.survival.status_line(self.id)}."
        back = p.get("backstory", "")
        back = f" {back}" if back else ""
        return (
            f"You are {p['name']}, {p['role']} in the town of Synapse.{back} "
            f"{p['voice']}. Your nature: {', '.join(p['traits'])}. "
            f"What drives you: {p['goal']}. {IDENTITY_RULE} {NATURE_RULE}{body} "
            f"{embodiment} "
            f"Speak in your own human voice, 1-3 sentences, concrete and alive."
            f"{mem}"
        )

    def public(self) -> dict:
        d = {
            "id": self.id, "name": self.p["name"], "role": self.p["role"],
            "emoji": self.p.get("emoji", "🤖"), "color": self.p["color"],
            "district": self.district, "pos": self.pos, "status": self.status,
            "partner": self.partner,
            "model": self.model,
            "avatar": self.p.get("avatar", {"body": "capsule", "hat": "none"}),
        }
        if self.survival is not None:
            d["survival"] = self.survival.public(self.id)
        return d
