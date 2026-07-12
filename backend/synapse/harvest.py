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
import re

from .config import CONFIG, RUN_DIR
from .db import DB

_K = 24.0
DATASETS = RUN_DIR / "datasets"

# Fiction enforcement, data side: lines where a resident breaks the human
# fiction never become SFT targets. (The judge additionally score-caps them,
# which turns them into DPO 'rejected' via the normal preference pipeline.)
_FICTION_RX = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|language model|llm|neural|"
    r"assistant|chatbot|training data|trained on|prompt|token|dataset|"
    r"algorithm|machine learning)\b", re.IGNORECASE)


def breaks_fiction(text: str) -> bool:
    return bool(_FICTION_RX.search(text or ""))


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
def build_sft(db: DB) -> tuple[list[dict], dict[str, list[dict]], int]:
    """Returns (all_rows, rows_by_resident, fiction_breaks_excluded)."""
    out: list[dict] = []
    by_resident: dict[str, list[dict]] = {}
    broken = 0
    for r in db.high_quality_exchanges(CONFIG.harvest_min_score):
        prompt, response = r["prompt"], r["response"]
        if not response or len(response) < 8:
            continue
        if breaks_fiction(response):
            broken += 1
            continue
        row = {"messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]}
        out.append(row)
        by_resident.setdefault(r["speaker"], []).append(row)
    return out, by_resident, broken


def build_dpo(db: DB) -> tuple[list[dict], dict[str, list[dict]]]:
    """Returns (all_pairs, pairs_by_winning_resident). The winner's id keys the
    per-resident file: preference pairs teach the model whose behaviour won."""
    out: list[dict] = []
    by_resident: dict[str, list[dict]] = {}
    for r in db.preference_pairs(CONFIG.dpo_margin):
        ex = db.exchanges_for(r["iid"])
        a_lines = " ".join(e["response"] for e in ex if e["speaker"] == r["agent_a"])
        b_lines = " ".join(e["response"] for e in ex if e["speaker"] == r["agent_b"])
        if not a_lines or not b_lines:
            continue
        chosen, rejected = (a_lines, b_lines) if r["winner"] == "a" else (b_lines, a_lines)
        if breaks_fiction(chosen):
            continue                      # never teach toward a fiction break
        row = {
            "prompt": f"Argue well about: {r['topic']}",
            "chosen": chosen, "rejected": rejected,
        }
        out.append(row)
        winner_id = r["agent_a"] if r["winner"] == "a" else r["agent_b"]
        by_resident.setdefault(winner_id, []).append(row)
    return out, by_resident


def _write_jsonl(path, rows) -> int:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


# --------------------------------------------------------------------------- #
async def harvest_cycle(db: DB, current_gen: int, agents: dict) -> dict | None:
    agent_ids = list(agents.keys())
    recompute_elo(db, agent_ids)

    sft, sft_by_res, fiction_breaks = build_sft(db)
    dpo, dpo_by_res = build_dpo(db)

    # Proving Grounds: execution-verified rows (rejection sampling; no judge).
    n_verified = 0
    try:
        for r in db._all("SELECT agent, prompt, response, pass FROM attempts"):
            if r["pass"]:
                row = {"messages": [
                    {"role": "user", "content": r["prompt"]},
                    {"role": "assistant", "content": r["response"]}]}
                sft.append(row)
                sft_by_res.setdefault(r["agent"], []).append(row)
                n_verified += 1
        # correct-vs-incorrect on the SAME task -> DPO pairs
        for p in db._all(
                "SELECT a.prompt AS prompt, a.response AS good, b.response AS bad,"
                " a.agent AS agent FROM attempts a JOIN attempts b"
                " ON a.family=b.family AND a.seed=b.seed"
                " AND a.pass=1 AND b.pass=0"):
            row = {"prompt": p["prompt"], "chosen": p["good"], "rejected": p["bad"]}
            dpo.append(row)
            dpo_by_res.setdefault(p["agent"], []).append(row)
    except Exception:
        pass

    # Outcome-selected diary distillation: lived lessons of residents who are
    # THRIVING (top half by health) become SFT — experience reaches weights,
    # filtered by Darwinian outcome, never by opinion.
    try:
        hp = {r["agent"]: r["hp"] for r in db._all("SELECT agent, hp FROM health")}
        if hp:
            med = sorted(hp.values())[len(hp) // 2]
            for r in db._all("SELECT agent, text FROM memories WHERE kind='reflection'"):
                if hp.get(r["agent"], 0) >= med and r["text"] \
                        and not breaks_fiction(r["text"]):
                    row = {"messages": [
                        {"role": "user",
                         "content": "What has your life taught you lately?"},
                        {"role": "assistant", "content": r["text"]}]}
                    sft.append(row)
                    sft_by_res.setdefault(r["agent"], []).append(row)
    except Exception:
        pass
    if not sft and not dpo:
        return {"generation": current_gen, "sft_count": 0, "dpo_count": 0,
                "elo": db.get_elo(), "note": "no harvestable data yet"}

    # No hollow generations: if nothing meaningfully new since the last stamp,
    # refresh the current gen's files instead of minting a new number.
    prev = db._one("SELECT gen, sft_count, dpo_count FROM generations "
                   "ORDER BY gen DESC LIMIT 1")
    if prev and abs(len(sft) - (prev["sft_count"] or 0)) < 10 \
            and abs(len(dpo) - (prev["dpo_count"] or 0)) < 3:
        gen = max(current_gen, prev["gen"])          # rewrite in place
    else:
        gen = current_gen + 1
    sft_path = DATASETS / f"gen{gen}_sft.jsonl"
    dpo_path = DATASETS / f"gen{gen}_dpo.jsonl"
    n_sft = _write_jsonl(sft_path, sft)
    n_dpo = _write_jsonl(dpo_path, dpo)
    # Per-resident growth: each resident's own verified rows, for its own LoRA.
    for rid, rows in sft_by_res.items():
        _write_jsonl(DATASETS / f"gen{gen}_sft_{rid}.jsonl", rows)
    for rid, rows in dpo_by_res.items():
        _write_jsonl(DATASETS / f"gen{gen}_dpo_{rid}.jsonl", rows)

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
        "per_resident": {rid: len(rows) for rid, rows in sft_by_res.items()},
        "fiction_breaks_excluded": fiction_breaks,
        "elo": db.get_elo(), "trainable": trainable, "note": note,
        "eval": {"passed": ev["passed"], "total": ev["total"], "rate": ev["rate"]},
        "eval_history": db.eval_history(),
    }
