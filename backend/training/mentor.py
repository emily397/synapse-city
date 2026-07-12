"""Phase 3 — Mentor night school (runs ~02:00, before the 03:00 train cycle).

The biggest model on the box (qwen2.5:32b) can't live in town (32B + pinned 14B
judge won't fit in 24GB), so it teaches at night while the town sleeps:

  1. unload every model from VRAM (frees the whole card for the 32B)
  2. the Mentor solves Proving-Grounds tasks (training seeds < 1M, never eval)
  3. each solution is EXECUTION-VERIFIED — only proven-correct answers count
  4. verified lessons are inserted as distillation rows for every student
     (family prefixed 'mentor:' so provenance is always auditable)
  5. unload the 32B, re-pin the 14B judge for the coming day

    python mentor.py --tasks 30
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evalsuite.families import FAMILIES, make_task      # noqa: E402
from evalsuite.run_suite import SYSTEM                  # noqa: E402
from evalsuite.verify import verify                     # noqa: E402

OLLAMA = "http://localhost:11434"
MENTOR = "qwen2.5:32b"
JUDGE = "qwen2.5:32b"
DB = HERE.parent / "run" / "synapse.db"
TRAIN_SEED_MAX = 1_000_000


def unload_all():
    try:
        ps = httpx.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])
        for m in ps:
            httpx.post(f"{OLLAMA}/api/generate",
                       json={"model": m["name"], "prompt": "", "keep_alive": 0,
                             "stream": False}, timeout=120)
            print(f"[unload] {m['name']}")
    except Exception as e:
        print("[warn] unload:", e)


def gen(model: str, prompt: str, keep: str = "10m") -> str:
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "keep_alive": keep,
        "options": {"temperature": 0.2, "num_predict": 700},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}]}, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"]


def main(n_tasks: int):
    con = sqlite3.connect(str(DB))
    students = [r[0] for r in con.execute(
        "SELECT DISTINCT speaker FROM exchanges").fetchall() if r[0]]
    if not students:
        print("no students yet"); return
    rng = random.Random(int(time.time()))
    unload_all()
    taught = 0
    for i in range(n_tasks):
        fam = rng.choice(sorted(FAMILIES))
        task = make_task(fam, rng.randrange(TRAIN_SEED_MAX))
        try:
            out = gen(MENTOR, task["prompt"])
            ok, _ = verify(task, out)
        except Exception as e:
            print(f"[{i+1}] error: {e}"); continue
        print(f"[{i+1}/{n_tasks}] {fam}: {'VERIFIED' if ok else 'rejected'}")
        if not ok:
            continue
        for s in students:
            con.execute(
                "INSERT INTO attempts(agent,family,seed,tick,pass,prompt,response)"
                " VALUES(?,?,?,?,1,?,?)",
                (s, "mentor:" + fam, task["seed"], 0, task["prompt"], out))
        taught += 1
    con.commit(); con.close()
    unload_all()
    # re-pin the judge for the day
    try:
        httpx.post(f"{OLLAMA}/api/generate",
                   json={"model": JUDGE, "prompt": "", "keep_alive": "24h",
                         "stream": False}, timeout=600)
        print("[ok] judge re-pinned")
    except Exception as e:
        print("[warn] judge pin:", e)
    print(f"night school done: {taught} verified lessons x {len(students)} students")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", type=int, default=30)
    main(ap.parse_args().tasks)
