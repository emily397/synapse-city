"""Peer teaching — residents learn from EACH OTHER, unprompted.

The town's own competence decides who teaches whom: for every task family, whoever
is STRONGEST at it (any architecture) becomes the teacher for whoever is weakest.
A Qwen resident strong at arithmetic teaches a Llama resident; the Llama teaches
string tasks back. A coder model teaches code; a reasoner teaches logic. Every
lesson is execution-verified, so only genuinely-correct knowledge transfers — and
it lands in the student's own corpus, so the next training cycle rewires the
student's weights toward the peer's strength. The 32B elder is the fallback
teacher only when NO peer is strong enough at a family. Runs nightly (autonomous).

    python peer_teach.py --per-family 6
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evalsuite.families import FAMILIES, make_task      # noqa: E402
from evalsuite.run_suite import SYSTEM                  # noqa: E402
from evalsuite.verify import verify                     # noqa: E402

OLLAMA = "http://localhost:11434"
DB = HERE.parent / "run" / "synapse.db"
PERSONAS = HERE.parent / "data" / "personas.json"
ELDER = "qwen2.5:32b"                 # fallback teacher when no peer is strong
TRAIN_SEED_MAX = 1_000_000
# native skill only — don't measure competence from what was already taught
NATIVE = "family NOT LIKE 'mentor:%' AND family NOT LIKE 'peer:%'"
WEAK = 0.5                            # student pass-rate below this = wants to learn
STRONG = 0.7                          # peer pass-rate at/above this = fit to teach


def gen(model: str, prompt: str) -> str:
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "keep_alive": "15m",
        "options": {"temperature": 0.2, "num_predict": 700},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}]}, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"]


def unload_all():
    try:
        for m in httpx.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", []):
            httpx.post(f"{OLLAMA}/api/generate",
                       json={"model": m["name"], "prompt": "", "keep_alive": 0,
                             "stream": False}, timeout=120)
    except Exception as e:
        print("[warn] unload:", e)


def competence(con):
    """{family: [(resident, pass_rate, n), ... strongest first]} from native skill."""
    by_fam = defaultdict(list)
    for r in con.execute(
            f"SELECT agent, family, SUM(pass) p, COUNT(*) n FROM attempts "
            f"WHERE {NATIVE} GROUP BY agent, family"):
        agent, fam, p, n = r[0], r[1], r[2] or 0, r[3]
        if fam in FAMILIES and n >= 2:
            by_fam[fam].append((agent, p / n, n))
    for fam in by_fam:
        by_fam[fam].sort(key=lambda x: (-x[1], -x[2]))
    return by_fam


def main(per_family: int, max_lessons: int, max_families: int = 0):
    con = sqlite3.connect(str(DB))
    models = {a["id"]: a["model"]
              for a in json.loads(PERSONAS.read_text(encoding="utf-8"))["agents"]}
    comp = competence(con)
    rng = random.Random(int(time.time()))

    # Build the teaching work-list and order by IMPACT (most weak students first)
    # so short, frequent runs still hit where it matters most.
    work = []
    for fam in FAMILIES:
        ranked = comp.get(fam, [])
        strong = [(a, r) for a, r, _ in ranked if r >= STRONG and a in models]
        weak = [a for a, r, _ in ranked if r < WEAK]
        if not weak:
            continue
        teacher_id, teacher_model, via = (strong[0][0], models[strong[0][0]], "peer") \
            if strong else (None, ELDER, "elder")
        students = [s for s in weak if s != teacher_id]
        if students:
            work.append((len(students), fam, teacher_id, teacher_model, via, students))
    work.sort(reverse=True)                      # most-needed families first
    if max_families:
        work = work[:max_families]
    if not work:
        print("nothing to teach — the town is even")
        return
    unload_all()

    taught = 0
    lessons_by_teacher = defaultdict(int)
    for _, fam, teacher_id, teacher_model, via, students in work:
        if taught >= max_lessons:
            break
        # generate a verified pool from the teacher, then hand to every weak student
        pool = []
        for _ in range(per_family * 3):
            if len(pool) >= per_family:
                break
            task = make_task(fam, rng.randrange(TRAIN_SEED_MAX))
            try:
                out = gen(teacher_model, task["prompt"])
                ok, _ = verify(task, out)
            except Exception as e:                       # noqa: BLE001
                print(f"[{fam}] {teacher_model} err: {e}")
                continue
            if ok:
                pool.append((task["seed"], task["prompt"], out))
        if not pool:
            print(f"[{fam}] teacher {teacher_model} couldn't verify any — skipped")
            continue
        label = f"peer:{teacher_id}:{fam}" if via == "peer" else f"mentor:{fam}"
        for s in students:
            for seed, prompt, out in pool:
                con.execute(
                    "INSERT INTO attempts(agent,family,seed,tick,pass,prompt,response)"
                    " VALUES(?,?,?,?,1,?,?)", (s, label, seed, 0, prompt, out))
                taught += 1
        lessons_by_teacher[teacher_id or "elder(32B)"] += len(pool)
        con.commit()
        who = f"{teacher_id}({teacher_model})" if via == "peer" else "elder 32B"
        print(f"[teach] {fam}: {who} -> {students}  ({len(pool)} lessons each)")
    con.close()
    unload_all()
    print("\n=== who taught this round (cross-model transfer) ===")
    for t, n in sorted(lessons_by_teacher.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n} verified lessons")
    print(f"total peer/elder lessons distributed: {taught}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-family", type=int, default=6)
    ap.add_argument("--max-lessons", type=int, default=300)
    ap.add_argument("--max-families", type=int, default=0,
                    help="cap families taught per run (0 = all) — keep it small for "
                         "short, frequent bursts that don't rest the town for long")
    a = ap.parse_args()
    main(a.per_family, a.max_lessons, a.max_families)
