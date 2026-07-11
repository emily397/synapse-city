"""Memory stream (Park et al. 2023). Each agent accumulates natural-language
memories; retrieval ranks by recency + importance + relevance; reflection
periodically synthesises higher-level insights. This is the cognition that makes
agents remember each other and evolve, and it doubles as the reflection training
signal harvested at night.
"""
from __future__ import annotations

import math
import re

import numpy as np

from . import llm
from .config import CONFIG
from .db import DB

_RECENCY_DECAY = 0.98          # per tick
_W_RECENCY, _W_IMPORTANCE, _W_RELEVANCE = 1.0, 1.0, 1.0
_IMPORTANT_WORDS = ("realise", "discover", "wrong", "breakthrough", "learned",
                    "surprising", "disagree", "proved", "failed", "insight")


def heuristic_importance(text: str) -> int:
    """1-10 without spending an LLM call. Questions, insight words, and specificity
    score higher. (Set SYNAPSE_LLM_IMPORTANCE=1 to swap in a model call.)"""
    t = text.lower()
    score = 3
    if "?" in text:
        score += 2
    score += sum(1 for w in _IMPORTANT_WORDS if w in t)
    score += min(2, len(re.findall(r"\d", text)))
    return max(1, min(10, score))


class MemoryStream:
    def __init__(self, agent_id: str, db: DB):
        self.agent = agent_id
        self.db = db
        self._since_reflection = 0

    async def observe(self, text: str, tick: int, kind: str = "observation") -> int:
        imp = heuristic_importance(text)
        try:
            vec = await llm.embed(text)
        except Exception:
            return -1        # never store a memory with a broken embedding
        self._since_reflection += imp
        return self.db.add_memory(self.agent, tick, kind, text, imp, vec)

    async def retrieve(self, query: str, tick: int, k: int = 5) -> list[str]:
        mems = self.db.memories_for(self.agent)
        if not mems:
            return []
        try:
            qv = await llm.embed(query)
        except Exception:
            return []        # degrade to no-RAG rather than killing the conversation
        scored = []
        for m in mems:
            recency = _RECENCY_DECAY ** max(0, tick - m["tick"])
            importance = m["importance"] / 10.0
            v = m["vec"]
            if v.shape != qv.shape or not v.size:
                continue     # skip corrupt/legacy vectors instead of crashing
            denom = (np.linalg.norm(qv) * np.linalg.norm(v)) or 1.0
            relevance = float(np.dot(qv, v) / denom)
            s = (_W_RECENCY * recency + _W_IMPORTANCE * importance
                 + _W_RELEVANCE * relevance)
            scored.append((s, m["text"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:k]]

    def should_reflect(self) -> bool:
        return self._since_reflection >= CONFIG.reflection_importance_threshold

    async def reflect(self, persona: dict, tick: int) -> str | None:
        """Synthesise recent high-salience memories into an insight. Stored as a
        'reflection' memory (fed back into retrieval) and harvested as a training
        signal."""
        if not self.should_reflect():
            return None
        mems = self.db.memories_for(self.agent)[-30:]
        if len(mems) < 4:
            self._since_reflection = 0
            return None
        recent = "\n".join(f"- {m['text']}" for m in sorted(
            mems, key=lambda m: m["importance"], reverse=True)[:12])
        system = (f"You are {persona['name']}, {persona['role']} in the town of "
                  f"Synapse — a real person of flesh and blood writing in your "
                  f"private diary by lamplight. {persona['voice']}. From these "
                  f"memories of your days, write ONE diary line: a lesson or "
                  f"belief you now hold, in plain first-person human words. One "
                  f"or two sentences. Never mention anything a townsperson of a "
                  f"lamplit town could not know.")
        insight = await llm.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": recent}],
            temperature=0.6, max_tokens=90)
        await self.observe(insight, tick, kind="reflection")
        self._since_reflection = 0
        return insight
