"""Model + resident registry. Lists the models Ollama is actually serving and
turns "add this model as a resident" requests into a persona (with an avatar
body) that the live town can spawn and persist."""
from __future__ import annotations

import json
import re

from .config import CONFIG

_BODIES = ["capsule", "sphere", "box", "cone"]
_HATS = ["none", "antenna", "cap", "beanie", "crown", "halo"]
_PALETTE = ["#3ba7ff", "#ff8a3d", "#37d67a", "#e0457b", "#b76bff",
            "#f2c94c", "#5cc8ff", "#ff6f91", "#8fd06f", "#ffb14e"]


def list_ollama_models() -> list[str]:
    """Model names Ollama is serving right now (empty in mock mode / if offline)."""
    if CONFIG.llm_backend != "ollama":
        return []
    try:
        import httpx
        r = httpx.get(f"{CONFIG.ollama_url}/api/tags", timeout=10)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "resident"


def _load() -> dict:
    return json.loads(CONFIG.personas_file.read_text(encoding="utf-8"))


def existing_ids() -> set[str]:
    return {a["id"] for a in _load()["agents"]}


def build_persona(spec: dict) -> dict:
    """spec: {name, model, role?, color?, home?, avatar?, voice?, goal?, traits?}."""
    ids = existing_ids()
    base = _slug(spec.get("name") or spec.get("model") or "resident")
    aid, i = base, 1
    while aid in ids:
        i += 1
        aid = f"{base}-{i}"
    n = len(ids)
    avatar = spec.get("avatar") or {}
    return {
        "id": aid,
        "name": spec.get("name") or spec.get("model") or aid,
        "role": spec.get("role") or "Resident",
        "emoji": spec.get("emoji") or "🤖",
        "color": spec.get("color") or _PALETTE[n % len(_PALETTE)],
        "home": spec.get("home") or "plaza",
        "model": spec.get("model") or "",
        "avatar": {
            "body": avatar.get("body") or spec.get("body") or _BODIES[n % len(_BODIES)],
            "hat": avatar.get("hat") or spec.get("hat") or _HATS[(n + 1) % len(_HATS)],
        },
        "traits": spec.get("traits") or ["curious", "sociable"],
        "expertise": spec.get("expertise") or "learning by talking to neighbours",
        "voice": spec.get("voice") or "friendly and thoughtful",
        "goal": spec.get("goal") or "learn from everyone in town",
        "is_judge": bool(spec.get("is_judge", False)),
    }


def save_persona(persona: dict) -> None:
    data = _load()
    if any(a["id"] == persona["id"] for a in data["agents"]):
        return
    data["agents"].append(persona)
    CONFIG.personas_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
