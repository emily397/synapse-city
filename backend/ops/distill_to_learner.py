"""Distill a strong teacher's VERIFIED solutions into a fresh learner's
curriculum. A brand-new weak resident (Sol, qwen2.5:0.5b) has no attempt history
for the failure-targeted mentor to work from, and it's weak at EVERYTHING — so we
teach it every family broadly. Each lesson is execution-verified (only correct
solutions become training signal), inserted as pass=1 attempts that the harvest
turns into the learner's SFT corpus. Run with the town paused (TRAINING.lock).

    python distill_to_learner.py --learner sol --teacher qwen2.5:14b --per-family 10
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from pathlib import Path

import httpx

TRAIN = Path(__file__).resolve().parent.parent / "training"
sys.path.insert(0, str(TRAIN))
from evalsuite.families import FAMILIES, make_task      # noqa: E402
from evalsuite.run_suite import SYSTEM                  # noqa: E402
from evalsuite.verify import verify                     # noqa: E402

OLLAMA = "http://localhost:11434"
DB = Path(__file__).resolve().parent.parent / "run" / "synapse.db"
TRAIN_SEED_MAX = 1_000_000


def gen(model: str, prompt: str) -> str:
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "keep_alive": "20m",
        "options": {"temperature": 0.2, "num_predict": 700},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}]}, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


def main(learner: str, teacher: str, per_family: int):
    con = sqlite3.connect(str(DB))
    rng = random.Random(int(time.time()))
    taught = 0
    fams = sorted(FAMILIES)
    print(f"distilling {teacher} -> {learner}: {per_family}/family across "
          f"{len(fams)} families")
    for fam in fams:
        got = 0
        for _ in range(per_family * 3):        # over-sample; keep only verified
            if got >= per_family:
                break
            task = make_task(fam, rng.randrange(TRAIN_SEED_MAX))
            try:
                out = gen(teacher, task["prompt"])
                ok, _ = verify(task, out)
            except Exception as e:             # noqa: BLE001
                print(f"[{fam}] err: {e}")
                continue
            if ok:
                con.execute(
                    "INSERT INTO attempts(agent,family,seed,tick,pass,prompt,response)"
                    " VALUES(?,?,?,?,1,?,?)",
                    (learner, "mentor:" + fam, task["seed"], 0, task["prompt"], out))
                got += 1
                taught += 1
        con.commit()
        print(f"[{fam}] taught {got}/{per_family}  (total {taught})")
    con.close()
    print(f"DONE: distilled {taught} verified lessons into {learner}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--learner", default="sol")
    ap.add_argument("--teacher", default="qwen2.5:14b")
    ap.add_argument("--per-family", type=int, default=10)
    a = ap.parse_args()
    main(a.learner, a.teacher, a.per_family)
