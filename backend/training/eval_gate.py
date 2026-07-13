"""Phase 2 (GPU): the promotion gate. A new adapter only reaches the live town if
it BEATS the incumbent on held-out probes, judged head-to-head with position
swaps (bias control) by the judge model. This is the single safeguard that stops
a collapsed or reward-hacked checkpoint from poisoning the town.

    python eval_gate.py --gen 3 --adapter dpo --incumbent qwen2.5:7b-instruct

Writes run/eval/gen3.json and prints PROMOTE / REJECT. On PROMOTE it records the
winning model tag to run/promoted.json, which the orchestrator reads.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import os

import httpx

from common import BASE_MODEL, MAX_SEQ, ADAPTERS, RUN

# WSL runs set SYNAPSE_OLLAMA_URL=http://<windows-host-ip>:11434
OLLAMA = os.getenv("SYNAPSE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
JUDGE_MODEL = os.getenv("SYNAPSE_EVAL_JUDGE", "qwen2.5:7b-instruct")
PROMOTE_MIN_WINRATE = 0.55
# Suite mode: promote only if the challenger beats the incumbent on discordant
# tasks with a one-sided sign test at this significance level.
SUITE_ALPHA = 0.05

PROBES = [
    "Argue whether disagreement makes a group smarter.",
    "Explain how a model could tell it is improving, concretely.",
    "Make the strongest case that imitation alone hits a ceiling.",
    "How would you measure understanding rather than recall?",
    "When does compression become intelligence? Defend a position.",
    "Give a concrete way to notice you are being fooled by a clever answer.",
]


def _ollama_gen(model: str, prompt: str) -> str:
    r = httpx.post(f"{OLLAMA}/api/generate",
                   json={"model": model, "prompt": prompt, "stream": False},
                   timeout=180)
    r.raise_for_status()
    return r.json()["response"].strip()


def _judge(prompt: str, first: str, second: str) -> str:
    """Return 'a' if `first` wins, 'b' if `second` wins."""
    sys = ('You are an impartial judge. Given a prompt and two answers, pick the '
           'stronger one on specificity, evidence, and logical tightness. '
           'Penalise clever-but-empty answers. Respond ONLY JSON: {"winner":"a"|"b"}.')
    user = f"PROMPT: {prompt}\n\nANSWER A:\n{first}\n\nANSWER B:\n{second}"
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": JUDGE_MODEL, "stream": False,
        "messages": [{"role": "system", "content": sys},
                     {"role": "user", "content": user}]}, timeout=180)
    r.raise_for_status()
    m = re.search(r'"winner"\s*:\s*"([ab])"', r.json()["message"]["content"])
    return m.group(1) if m else "b"


def _sign_test_p(wins: int, losses: int) -> float:
    """One-sided sign test: P(challenger wins >= observed | fair coin) over
    discordant pairs. Small p => the win pattern is unlikely to be luck."""
    import math
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def main(gen: int, which: str, incumbent: str, suite: str | None = None):
    from unsloth import FastLanguageModel
    adapter = ADAPTERS / f"gen{gen}-{which}"
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(adapter), max_seq_length=MAX_SEQ, load_in_4bit=True)
    FastLanguageModel.for_inference(model)

    def challenger_gen(prompt: str, sys_prompt: str | None = None,
                       max_new: int = 220, temp: float = 0.7) -> str:
        msgs = ([{"role": "system", "content": sys_prompt}] if sys_prompt else []) + \
               [{"role": "user", "content": prompt}]
        ids = tokenizer.apply_chat_template(msgs, return_tensors="pt",
                                            add_generation_prompt=True).to(model.device)
        out = model.generate(input_ids=ids, max_new_tokens=max_new,
                             temperature=max(temp, 1e-5), do_sample=temp > 0)
        return tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()

    if suite:
        def free_challenger():
            # release the challenger's VRAM so a large incumbent can load on the
            # same 24GB card (they cannot both be resident at once for 14B+)
            import gc
            import torch
            nonlocal model, tokenizer
            try:
                del model, tokenizer
            except Exception:
                pass
            gc.collect()
            torch.cuda.empty_cache()
        return _suite_gate(gen, challenger_gen, incumbent, suite, free_challenger)

    wins = 0.0
    records = []
    for p in PROBES:
        ch = challenger_gen(p)
        inc = _ollama_gen(incumbent, p)
        # Position-swapped judging: challenger as A, then as B. Average.
        w1 = _judge(p, ch, inc)      # a == challenger
        w2 = _judge(p, inc, ch)      # b == challenger
        score = (1.0 if w1 == "a" else 0.0) + (1.0 if w2 == "b" else 0.0)
        wins += score / 2.0
        records.append({"probe": p, "challenger": ch, "incumbent": inc,
                        "round_score": score / 2.0})

    winrate = wins / len(PROBES)
    promote = winrate >= PROMOTE_MIN_WINRATE
    tag = f"synapse-gen{gen}"

    (RUN / "eval").mkdir(exist_ok=True)
    (RUN / "eval" / f"gen{gen}.json").write_text(json.dumps({
        "gen": gen, "winrate": winrate, "promote": promote,
        "incumbent": incumbent, "challenger_tag": tag, "records": records}, indent=2))

    print(f"[eval] gen{gen} winrate={winrate:.2f} vs {incumbent} "
          f"-> {'PROMOTE' if promote else 'REJECT'}")
    if promote:
        (RUN / "promoted.json").write_text(json.dumps(
            {"gen": gen, "model": tag, "winrate": winrate}))
    return promote


def _suite_gate(gen: int, challenger_gen, incumbent: str, suite: str,
                free_challenger) -> bool:
    """Execution-verified gate, TWO-PHASE so challenger and incumbent never
    fight for VRAM: (1) generate every challenger answer while its weights are
    on the GPU, (2) FREE the challenger, (3) load the incumbent and answer the
    same tasks. Promote only if challenger's pass rate >= incumbent's AND a
    one-sided sign test over discordant tasks rejects luck (p < alpha)."""
    import sys as _sys
    import time as _t
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from evalsuite.run_suite import SYSTEM, load_suite, ollama_chat
    from evalsuite.verify import verify

    tasks = load_suite(Path(__file__).resolve().parent / "evalsuite" / suite)
    # nightly gate uses a fast deterministic subset (still statistically valid
    # via the sign test); the full 160-task suite is the weekly deep eval.
    import os as _os
    gate_n = int(_os.getenv("SYNAPSE_GATE_TASKS", "64"))
    if gate_n and gate_n < len(tasks):
        step = max(1, len(tasks) // gate_n)
        tasks = tasks[::step][:gate_n]

    # --- PHASE 1: challenger answers (its weights are in VRAM now) ---------
    ch_ok_list = []
    for i, t in enumerate(tasks, 1):
        try:
            out = challenger_gen(t["prompt"], sys_prompt=SYSTEM,
                                 max_new=512, temp=0.0)
            ok, _ = verify(t, out)
        except Exception:                            # noqa: BLE001
            ok = False
        ch_ok_list.append(bool(ok))
        if i % 40 == 0:
            print(f"[gate] challenger {i}/{len(tasks)}")

    # --- free the challenger so the incumbent can load on the same card ----
    free_challenger()
    _t.sleep(12)                             # let the CUDA allocator hand VRAM
                                             # back before Ollama tries to load

    # incumbent must actually be servable now that VRAM is free; give a big
    # model generous time to load, but never gate against a dead baseline. Log
    # the real error each miss so a persistent failure is diagnosable, not silent.
    last_err = ""
    for attempt in range(15):
        try:
            ollama_chat(incumbent, "say OK")
            break
        except Exception as e:               # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            print(f"[gate] incumbent warmup {attempt + 1}/15 failed: {last_err}")
            _t.sleep(15)
    else:
        raise SystemExit(f"incumbent {incumbent} unreachable after 15 tries "
                         f"(last: {last_err}) — refusing to gate against a dead "
                         f"baseline")

    # --- PHASE 2: incumbent answers ---------------------------------------
    inc_ok_list = []
    for i, t in enumerate(tasks, 1):
        ok = False
        for _try in range(2):
            try:
                ok, _ = verify(t, ollama_chat(incumbent, t["prompt"]))
                break
            except Exception:                        # noqa: BLE001
                _t.sleep(3)
        inc_ok_list.append(bool(ok))
        if i % 40 == 0:
            print(f"[gate] incumbent {i}/{len(tasks)}")

    ch_pass = sum(ch_ok_list)
    inc_pass = sum(inc_ok_list)
    ch_wins = sum(1 for c, ii in zip(ch_ok_list, inc_ok_list) if c and not ii)
    inc_wins = sum(1 for c, ii in zip(ch_ok_list, inc_ok_list) if ii and not c)
    records = [{"id": tasks[i]["id"], "challenger": ch_ok_list[i],
                "incumbent": inc_ok_list[i]} for i in range(len(tasks))]
    n = len(tasks)
    p = _sign_test_p(ch_wins, inc_wins)
    promote = ch_pass >= inc_pass and p < SUITE_ALPHA
    tag = f"synapse-gen{gen}"
    (RUN / "eval").mkdir(exist_ok=True)
    (RUN / "eval" / f"gen{gen}.json").write_text(json.dumps({
        "gen": gen, "mode": "suite", "suite": suite, "n": n,
        "challenger_rate": ch_pass / n, "incumbent_rate": inc_pass / n,
        "discordant": {"challenger_wins": ch_wins, "incumbent_wins": inc_wins},
        "sign_test_p": p, "promote": promote, "incumbent": incumbent,
        "challenger_tag": tag, "records": records}, indent=2))
    print(f"[eval] gen{gen} suite: challenger {ch_pass}/{n} vs incumbent "
          f"{inc_pass}/{n}, discordant +{ch_wins}/-{inc_wins}, p={p:.4f} "
          f"-> {'PROMOTE' if promote else 'REJECT'}")
    if promote:
        (RUN / "promoted.json").write_text(json.dumps(
            {"gen": gen, "model": tag, "rate": ch_pass / n, "p": p}))
    return promote


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--adapter", choices=["sft", "dpo"], default="dpo")
    ap.add_argument("--incumbent", default="qwen2.5:7b-instruct")
    ap.add_argument("--suite", default=None,
                    help="suite filename in evalsuite/ (e.g. suite_v1.jsonl); "
                         "omit for legacy judge-probe mode")
    a = ap.parse_args()
    raise SystemExit(0 if main(a.gen, a.adapter, a.incumbent, a.suite) else 1)
