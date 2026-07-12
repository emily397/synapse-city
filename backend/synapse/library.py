"""Phases 4-5: the Town Library — shared knowledge that outlives its discoverer,
and skills the residents author themselves.

LIBRARY NOTES: each new day, the day's best material is distilled into
standalone notes (claim + source), embedded, and stored SHARED — any resident's
conversation can retrieve town wisdom regardless of who learned it. Knowledge
compounds across residents instead of dying with its owner.

SKILLS: when a resident has solved a task family 3+ times, its own model writes
a short playbook (name, when-to-use, steps). Skills are retrieved into matching
future Proving-Grounds attempts. Per-skill lift is tracked (pass rate with vs
without); skills that don't lift can be archived. Skill-then-success
trajectories are premium SFT (the model learns to abstract its own procedures).
"""
from __future__ import annotations

import numpy as np

from . import llm
from .bus import BUS
from .db import DB


class Library:
    def __init__(self, db: DB):
        self.db = db
        auto = "INTEGER PRIMARY KEY AUTOINCREMENT" if not db.pg else "SERIAL PRIMARY KEY"
        db._run(f"CREATE TABLE IF NOT EXISTS library ("
                f" id {auto}, kind TEXT, claim TEXT, source TEXT, day INTEGER,"
                f" embedding BLOB)")
        db._run(f"CREATE TABLE IF NOT EXISTS skills ("
                f" id {auto}, agent TEXT, family TEXT, name TEXT, playbook TEXT,"
                f" used INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,"
                f" archived INTEGER DEFAULT 0)")

    # ------------------------------------------------------------- notes -- #
    async def add_note(self, kind: str, claim: str, source: str, day: int):
        if not claim or len(claim) < 20:
            return
        try:
            vec = await llm.embed(claim)
        except Exception:
            return
        self.db._run("INSERT INTO library(kind,claim,source,day,embedding)"
                     " VALUES(?,?,?,?,?)",
                     (kind, claim[:500], source, day, vec.tobytes()))

    async def retrieve(self, query: str, k: int = 2) -> list[str]:
        rows = self.db._all("SELECT claim, embedding FROM library")
        if not rows:
            return []
        try:
            qv = await llm.embed(query)
        except Exception:
            return []
        scored = []
        for r in rows:
            v = np.frombuffer(bytes(r["embedding"]), dtype=np.float32)
            if v.shape != qv.shape or not v.size:
                continue
            scored.append((float(np.dot(qv, v)), r["claim"]))
        scored.sort(reverse=True)
        return [c for _, c in scored[:k]]

    async def nightly_distill(self, db: DB, day: int) -> int:
        """Distill the day's best material into shared notes."""
        n = 0
        # winning arguments (judged, high score)
        for r in db._all(
                "SELECT j.reason AS why, j.winner, j.agent_a, j.agent_b, i.topic "
                "FROM judgements j JOIN interactions i ON i.id=j.interaction_id "
                "ORDER BY j.id DESC LIMIT 5"):
            w = r["agent_a"] if r["winner"] == "a" else r["agent_b"]
            if r["why"]:
                await self.add_note("argument",
                                    f"On {r['topic']}: {r['why']}", w, day)
                n += 1
        # top diary reflections
        for r in db._all("SELECT agent, text FROM memories WHERE kind='reflection' "
                         "ORDER BY id DESC LIMIT 5"):
            await self.add_note("wisdom", r["text"], r["agent"], day)
            n += 1
        if n:
            BUS.publish({"type": "toast",
                         "text": f"📚 The Town Library grew by {n} entries"})
        return n

    # ------------------------------------------------------------ skills -- #
    async def maybe_author_skill(self, agent, family: str, tick: int):
        """3+ verified solves in a family -> the resident writes its playbook."""
        if self.db._one("SELECT id FROM skills WHERE agent=? AND family=?",
                        (agent.id, family)):
            return
        n = self.db._one("SELECT COUNT(*) AS n FROM attempts WHERE agent=? "
                         "AND family=? AND pass=1", (agent.id, family))
        if not n or n["n"] < 3:
            return
        ex = self.db._all("SELECT prompt, response FROM attempts WHERE agent=? "
                          "AND family=? AND pass=1 ORDER BY id DESC LIMIT 2",
                          (agent.id, family))
        worked = "\n---\n".join(e["response"][:400] for e in ex)
        try:
            out = await llm.chat(
                [{"role": "system", "content":
                  "You are a precise craftsperson writing a private playbook."},
                 {"role": "user", "content":
                  f"You have repeatedly solved puzzles of one kind. From these "
                  f"worked solutions:\n{worked}\n\nWrite a SHORT playbook:\n"
                  f"NAME: <method name>\nWHEN: <when to use it>\n"
                  f"STEPS: <3-5 numbered steps>"}],
                model=agent.model, temperature=0.4, max_tokens=250)
            self.db._run("INSERT INTO skills(agent,family,name,playbook)"
                         " VALUES(?,?,?,?)",
                         (agent.id, family, family, out[:800]))
            BUS.publish({"type": "toast",
                         "text": f"📖 {agent.p['name']} wrote a playbook for "
                                 f"{family.replace('_', ' ')}"})
            await agent.mem.observe(
                "I wrote down my method for a kind of puzzle I keep solving.",
                tick, kind="survival")
        except Exception:
            pass

    def skill_for(self, agent_id: str, family: str) -> str | None:
        r = self.db._one("SELECT id, playbook FROM skills WHERE agent=? AND "
                         "family=? AND archived=0", (agent_id, family))
        if r:
            self.db._run("UPDATE skills SET used=used+1 WHERE id=?", (r["id"],))
            return r["playbook"]
        return None

    def record_skill_win(self, agent_id: str, family: str):
        self.db._run("UPDATE skills SET wins=wins+1 WHERE agent=? AND family=? "
                     "AND archived=0", (agent_id, family))
