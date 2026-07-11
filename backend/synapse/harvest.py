"""Self-learning harvest (Phase 2, data side).

On each new day we:
  1. recompute live per-agent ELO from real Arena judgements (honest signal:
     which persona actually argues best),
  2. build SFT dataset from high-scoring exchanges,
  3. build DPO preference dataset from judged debates (chosen vs rejected),
  4. write JSONL under run/datasets/ and stamp a new generation.

The GPU-side training (Unsloth QLoRA + DPO + eval-gate + Ollama promote) lives in
backend/training/ and consumes these files. Datasets here are REAL (built from
whatever conversations happened, mock or Ollama). ELO here is REAL. Model
promotion winrate becomes real only when you run the trainer; until then a
generation is marked "datasets built, training pending".
"""
from __future__ import annotations

import json

from .config import CONFIG, RUN_DIR
from .db import DB

_K = 24.0
DATASETS = RUN_DIR / "datasets"


# --------------------------------------------------------------------------- #
def recompute_elo(db: DB, agent_ids: list[str]) -> None:
    rating = {a: 1000.0 for a in agent_ids}
    games = {a: 0 for a in agent_ids}
    rows = db.conn.execute(
        "SELECT agent_a, agent_b, winner FROM judgements ORDER BY id").fetchall()
    for r in rows:
        a, b, w = r["agent_a"], r["agent_b"], r["winner"]
        if a not in rating or b not in rating:
            continue
        ea = 1.0 / (1.0 + 10 ** ((rating[b] - rating[a]) / 400))
        sa = 1.0 if w == "a" else 0.0
        rating[a] += _K * (sa - ea)
        rating[b] += _K * ((1 - sa) - (1 - ea))
        games[a] += 1
        games[b] += 1
    for a in agent_ids:
        db.set_elo(a, round(rating[a], 1), games[a])


# --------------------------------------------------------------------------- #
def build_sft(db: DB) -> list[dict]:
    out = []
    for r in db.high_quality_exchanges(CONFIG.harvest_min_score):
        prompt, response = r["prompt"], r["response"]
        if not response or len(response) < 8:
            continue
        out.append({"messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]})
    return out


def build_dpo(db: DB) -> list[dict]:
    out = []
    for r in db.preference_pairs(CONFIG.dpo_margin):
        ex = db.exchanges_for(r["iid"])
        a_lines = " ".join(e["response"] for e in ex if e["speaker"] == r["agent_a"])
        b_lines = " ".join(e["response"] for e in ex if e["speaker"] == r["agent_b"])
        if not a_lines or not b_lines:
            continue
        chosen, rejected = (a_lines, b_lines) if r["winner"] == "a" else (b_lines, a_lines)
        out.append({
            "prompt": f"Argue well about: {r['topic']}",
            "chosen": chosen, "rejected": rejected,
        })
    return out


def _write_jsonl(path, rows) -> int:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


# --------------------------------------------------------------------------- #
async def harvest_cycle(db: DB, current_gen: int, agents: dict) -> dict | None:
    agent_ids = list(agents.keys())
    recompute_elo(db, agent_ids)

    sft = build_sft(db)
    dpo = build_dpo(db)
    if not sft and not dpo:
        return {"generation": current_gen, "sft_count": 0, "dpo_count": 0,
                "elo": db.get_elo(), "note": "no harvestable data yet"}

    gen = current_gen + 1
    sft_path = DATASETS / f"gen{gen}_sft.jsonl"
    dpo_path = DATASETS / f"gen{gen}_dpo.jsonl"
    n_sft = _write_jsonl(sft_path, sft)
    n_dpo = _write_jsonl(dpo_path, dpo)

    trainable = CONFIG.llm_backend == "ollama"
    note = ("datasets built, ready to train" if trainable
            else "datasets built (mock text); wire Ollama to train for real")
    db.record_generation(gen, n_sft, n_dpo, note)

    # Objective, code-verified quality axis (second real metric beside ELO).
    from . import selfeval
    ev = await selfeval.run_eval()
    db.add_eval_run(gen, ev["passed"], ev["total"], ev["rate"], ev["model"])

    return {
        "generation": gen, "sft_count": n_sft, "dpo_count": n_dpo,
        "sft_path": str(sft_path), "dpo_path": str(dpo_path),
        "elo": db.get_elo(), "trainable": trainable, "note": note,
        "eval": {"passed": ev["passed"], "total": ev["total"], "rate": ev["rate"]},
        "eval_history": db.eval_history(),
    }
