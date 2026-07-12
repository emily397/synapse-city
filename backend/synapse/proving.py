"""Proving Grounds (Phase 1): execution-verified tasks residents attempt during
the day. Correct solutions become SFT rows; correct-vs-incorrect on the same
task become DPO pairs. The judge's opinion no longer gates this fuel —
execution does.

Task generators are shared with the eval suite (training uses seeds < 1_000_000;
eval owns >= 1_000_000, so the gate stays held-out by construction). Attempts
are the resident's PRIVATE study — raw model reasoning stored for training —
while the in-world memory only says they worked the workshop puzzle board, so
the human fiction never breaks.

Curriculum: per-resident, per-family success is tracked; each pick favours the
family whose success rate sits closest to the 50% learning zone.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from evalsuite.families import FAMILIES, make_task          # noqa: E402
from evalsuite.verify import verify                        # noqa: E402

from . import llm
from .bus import BUS
from .db import DB

TRAIN_SEED_MAX = 1_000_000          # eval seeds live above this line
TARGET = 0.5                        # learning-zone centre

SYSTEM = ("You are a precise problem solver. For coding tasks reply with ONE "
          "```python code block defining the requested function. For other "
          "tasks, think briefly then end with the exact final line "
          "'ANSWER: <value>'.")


class ProvingGrounds:
    def __init__(self, db: DB):
        self.db = db
        db._run("CREATE TABLE IF NOT EXISTS attempts ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, family TEXT,"
                " seed INTEGER, tick INTEGER, pass INTEGER, prompt TEXT,"
                " response TEXT)" if not db.pg else
                "CREATE TABLE IF NOT EXISTS attempts ("
                " id SERIAL PRIMARY KEY, agent TEXT, family TEXT, seed INTEGER,"
                " tick INTEGER, pass INTEGER, prompt TEXT, response TEXT)")
        self.busy: set[str] = set()
        self.library = None                # set by the simulation

    def _pick_family(self, aid: str, rng: random.Random) -> str:
        stats = {f: (0, 0) for f in FAMILIES}
        for r in self.db._all(
                "SELECT family, SUM(pass) AS p, COUNT(*) AS n FROM attempts "
                "WHERE agent=? GROUP BY family", (aid,)):
            stats[r["family"]] = (r["p"] or 0, r["n"])
        def zone(f):
            p, n = stats[f]
            if n < 3:
                return 0.0                       # unexplored families first
            return abs((p / n) - TARGET)
        fams = sorted(FAMILIES, key=zone)
        return rng.choice(fams[:5])              # near the learning zone

    async def attempt(self, agent, tick: int, rng: random.Random) -> None:
        """One resident privately works a puzzle. Fire-and-forget async."""
        aid = agent.id
        if aid in self.busy:
            return
        self.busy.add(aid)
        try:
            fam = self._pick_family(aid, rng)
            seed = rng.randrange(TRAIN_SEED_MAX)
            task = make_task(fam, seed)
            sys_p = SYSTEM
            used_skill = False
            if self.library is not None:
                pb = self.library.skill_for(aid, fam)
                if pb:
                    sys_p += f"\n\nYour own proven playbook for this kind:\n{pb}"
                    used_skill = True
            out = await llm.chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": task["prompt"]}],
                model=agent.model, temperature=0.3, max_tokens=700)
            ok, _detail = verify(task, out)
            if self.library is not None:
                if ok and used_skill:
                    self.library.record_skill_win(aid, fam)
                if ok:
                    await self.library.maybe_author_skill(agent, fam, tick)
            self.db._run(
                "INSERT INTO attempts(agent,family,seed,tick,pass,prompt,response)"
                " VALUES(?,?,?,?,?,?,?)",
                (aid, fam, seed, tick, 1 if ok else 0, task["prompt"], out))
            BUS.publish({"type": "toast",
                         "text": f"{agent.p['name']} {'cracked' if ok else 'wrestled with'} "
                                 f"a puzzle at the workshop board {'🧩' if ok else '…'}"})
            await agent.mem.observe(
                f"I {'solved' if ok else 'could not solve'} a hard puzzle from "
                f"the workshop board today.", tick, kind="survival")
        except Exception:
            pass
        finally:
            self.busy.discard(aid)
