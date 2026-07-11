"""LLM gateway. One interface, two backends:

  * "ollama" : real local models on the RTX 3090 (chat + embeddings)
  * "mock"   : deterministic, dependency-free brain so the whole town runs and
               looks alive on any machine (CPU, no GPU, no network).

Nothing else in the codebase talks to a model directly; everything goes through
chat() / embed() / complete_json().
"""
from __future__ import annotations

import json
import re
import hashlib
import random
from typing import Any

import numpy as np

from .config import CONFIG

EMBED_DIM = 256


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
async def chat(messages: list[dict], *, model: str | None = None,
               temperature: float | None = None, max_tokens: int | None = None) -> str:
    model = model or CONFIG.chat_model
    temperature = CONFIG.temperature if temperature is None else temperature
    max_tokens = max_tokens or CONFIG.max_tokens
    if CONFIG.llm_backend == "ollama":
        return await _ollama_chat(messages, model, temperature, max_tokens)
    return _mock_chat(messages, temperature)


async def complete_json(messages: list[dict], *, model: str | None = None) -> dict:
    """Chat call expected to return a JSON object. Robust to junk around it."""
    raw = await chat(messages, model=model, temperature=0.2, max_tokens=400)
    return _extract_json(raw)


async def embed(text: str) -> np.ndarray:
    if CONFIG.llm_backend == "ollama":
        return await _ollama_embed(text)
    return _mock_embed(text)


# --------------------------------------------------------------------------- #
# Ollama backend
# --------------------------------------------------------------------------- #
async def _ollama_chat(messages, model, temperature, max_tokens) -> str:
    import httpx
    payload = {
        "model": model, "messages": messages, "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{CONFIG.ollama_url}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


async def _ollama_embed(text: str) -> np.ndarray:
    import httpx
    async with httpx.AsyncClient(timeout=60) as c:
        for attempt in (0, 1):
            r = await c.post(f"{CONFIG.ollama_url}/api/embeddings",
                             json={"model": CONFIG.embed_model, "prompt": text})
            r.raise_for_status()
            v = np.asarray(r.json().get("embedding") or [], dtype=np.float32)
            if v.size:                      # Ollama can return [] mid-restart
                break
    if not v.size:
        raise RuntimeError("empty embedding from Ollama (server restarting?)")
    n = np.linalg.norm(v)
    return v / n if n else v


# --------------------------------------------------------------------------- #
# Mock backend (deterministic, offline)
# --------------------------------------------------------------------------- #
def _seed_from(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:12], 16)


def _mock_embed(text: str) -> np.ndarray:
    """Hashed bag-of-words embedding. Not semantic, but stable and good enough to
    order memories by overlap in the offline demo."""
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    for tok in re.findall(r"[a-z0-9']+", text.lower()):
        idx = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % EMBED_DIM
        v[idx] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


# Persona-flavoured sentence fragments, keyed by role, used to synthesise
# coherent-sounding dialogue offline.
_ROLE_STYLE = {
    "Scientist": [
        "What's the actual mechanism behind {t}?",
        "If {t} holds, then we'd expect a measurable effect. Do we see it?",
        "Let's isolate the variable. Strip {t} down to first principles.",
        "My hypothesis on {t}: the causal arrow runs the other way.",
    ],
    "Engineer": [
        "Fine in theory. To ship {t} you'd wire it in three steps.",
        "I'd prototype {t} today and measure, not argue.",
        "The bottleneck in {t} is state, not compute. Cache it.",
        "Give me an interface for {t} and I'll have it running.",
    ],
    "Teacher": [
        "Here's {t} in one line: it's just a feedback loop with memory.",
        "Think of {t} like a garden. You plant, you prune, it grows.",
        "Break {t} into what changes and what stays fixed. Then it's simple.",
        "Good question. The part people miss about {t} is the boundary case.",
    ],
    "Skeptic": [
        "That claim about {t} is doing a lot of work. Where's the evidence?",
        "Steelman first: best case for {t}. Now here's where it breaks.",
        "Counterexample for {t}: it fails the moment inputs go adversarial.",
        "You're assuming {t} generalises. It doesn't, and here's why.",
    ],
    "Creative": [
        "What if {t} worked like a coral reef instead of a machine?",
        "Flip it: what would {t} look like run backwards?",
        "Mash {t} with jazz improv and you get something new.",
        "Boring framing. Let's reimagine {t} from the user's dream, not the spec.",
    ],
    "Mentor & Judge": [
        "Both landed points on {t}. Let me weigh them against the rubric.",
        "Strongest argument on {t} was the concrete one, not the clever one.",
        "I'm marking down the hand-wavy claim on {t}. Specificity wins.",
    ],
}
_TOPICS = [
    "self-improving agents", "memory and forgetting", "why models collapse",
    "the value of disagreement", "emergent behaviour", "how to measure understanding",
    "curiosity as a signal", "the limits of imitation", "teaching versus telling",
    "reward hacking", "what makes an argument strong", "compression as intelligence",
]


def _topic_from(messages: list[dict], rng: random.Random) -> str:
    for m in reversed(messages):
        if m["role"] == "user":
            words = re.findall(r"[A-Za-z][A-Za-z\-]{4,}", m["content"])
            if words:
                return " ".join(w.lower() for w in words[:3])
    return rng.choice(_TOPICS)


def _mock_chat(messages: list[dict], temperature: float) -> str:
    system = next((m["content"] for m in messages if m["role"] == "system"), "")

    # Judge / scoring calls: return structured JSON so complete_json() works offline.
    if "JSON" in system or "rubric" in system.lower() or "score" in system.lower():
        rng = random.Random(_seed_from(system, messages[-1]["content"]))
        a, b = round(rng.uniform(4, 9.5), 1), round(rng.uniform(4, 9.5), 1)
        return json.dumps({
            "score_a": a, "score_b": b,
            "winner": "a" if a >= b else "b",
            "reason": "Rated on specificity, evidence, and logical tightness.",
        })

    role = _role_of(system)
    rng = random.Random(_seed_from(system, str(len(messages)), messages[-1]["content"]))
    topic = _topic_from(messages, rng)
    bank = _ROLE_STYLE.get(role, _ROLE_STYLE["Scientist"])
    n = 1 if temperature < 0.5 else rng.choice([1, 2, 2, 3])
    picks = rng.sample(bank, k=min(n, len(bank)))
    return " ".join(p.format(t=topic) for p in picks)


def _role_of(system: str) -> str:
    for role in _ROLE_STYLE:
        if role.lower() in system.lower():
            return role
    return "Scientist"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
