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


def weak_families(con, student, min_attempts=2, pass_ceiling=0.6):
    """Families this student actually WORKS ON (has real attempts) but is weak at
    (pass-rate below the ceiling). These are its learning frontier — teaching it
    what it already solves adds nothing and only specialises it off-distribution.
    Excludes prior 'mentor:' rows so we don't chase our own tail."""
    rows = con.execute(
        "SELECT family, COALESCE(SUM(pass),0) p, COUNT(*) n FROM attempts "
        "WHERE agent=? AND family NOT LIKE 'mentor:%' GROUP BY family",
        (student,)).fetchall()
    weak = []
    for fam, p, n in rows:
        if fam in FAMILIES and n >= min_attempts and (p / n) < pass_ceiling:
            weak.append((fam, p / n, n))
    weak.sort(key=lambda x: x[1])                # weakest first
    return [w[0] for w in weak]


def main(n_per_family: int, max_lessons: int = 200):
    con = sqlite3.connect(str(DB))
    students = [r[0] for r in con.execute(
        "SELECT DISTINCT speaker FROM exchanges").fetchall() if r[0]]
    if not students:
        print("no students yet"); return
    rng = random.Random(int(time.time()))
    unload_all()

    # Which student is weak in which family (targeted; follows what they work on).
    weak_by_student = {s: weak_families(con, s) for s in students}
    families_needed = sorted({f for fams in weak_by_student.values() for f in fams})
    print(f"[mentor] {len(students)} students; weak families to teach: "
          f"{families_needed or '(none yet — need more attempts logged)'}")

    # Solve each needed family ONCE into a shared verified pool (fresh seeds, so
    # the METHOD is taught, not a memorised instance), then distribute each
    # family's lessons only to the students actually weak in it.
    taught = 0
    for fam in families_needed:
        if taught >= max_lessons:
            break
        pool = []
        for _ in range(n_per_family * 3):        # over-sample; keep the verified
            if len(pool) >= n_per_family:
                break
            task = make_task(fam, rng.randrange(TRAIN_SEED_MAX))
            try:
                out = gen(MENTOR, task["prompt"])
                ok, _ = verify(task, out)
            except Exception as e:               # noqa: BLE001
                print(f"[{fam}] error: {e}"); continue
            if ok:
                pool.append((task["seed"], task["prompt"], out))
        if not pool:
            print(f"[{fam}] mentor could not verify any solution — skipping")
            continue
        recipients = [s for s in students if fam in weak_by_student[s]]
        for s in recipients:
            for seed, prompt, out in pool:
                con.execute(
                    "INSERT INTO attempts(agent,family,seed,tick,pass,prompt,response)"
                    " VALUES(?,?,?,?,1,?,?)",
                    (s, "mentor:" + fam, seed, 0, prompt, out))
                taught += 1
        print(f"[teach] {fam}: {len(pool)} verified lessons -> "
              f"{len(recipients)} weak students")
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
    ap.add_argument("--per-family", type=int, default=4,
                    help="verified fresh instances the mentor teaches per weak family")
    ap.add_argument("--max-lessons", type=int, default=300)
    ap.add_argument("--tasks", type=int, default=None,
                    help="(deprecated; ignored) kept for supervisor compatibility")
    a = ap.parse_args()
    main(a.per_family, a.max_lessons)
