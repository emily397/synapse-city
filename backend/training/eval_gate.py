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
        return _suite_gate(gen, challenger_gen, incumbent, suite)

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


def _suite_gate(gen: int, challenger_gen, incumbent: str, suite: str) -> bool:
    """Execution-verified gate: challenger vs incumbent on the frozen held-out
    suite. Promote only if (a) challenger's pass rate is >= incumbent's and
    (b) a one-sided sign test over discordant tasks rejects luck (p < alpha)."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from evalsuite.run_suite import SYSTEM, load_suite, ollama_chat
    from evalsuite.verify import verify

    tasks = load_suite(Path(__file__).resolve().parent / "evalsuite" / suite)
    # incumbent must actually be servable: warm it up, fail loudly if not.
    # (a dead incumbent scored 0% in gen1 and silently corrupted the gate)
    for _ in range(3):
        try:
            ollama_chat(incumbent, "say OK", )
            break
        except Exception:
            import time as _t
            _t.sleep(20)
    else:
        raise SystemExit(f"incumbent {incumbent} unreachable — refusing to gate "
                         f"against a dead baseline")
    ch_wins = inc_wins = 0
    ch_pass = inc_pass = 0
    records = []
    for i, t in enumerate(tasks, 1):
        try:
            ch_out = challenger_gen(t["prompt"], sys_prompt=SYSTEM,
                                    max_new=700, temp=0.0)
            ch_ok, _ = verify(t, ch_out)
        except Exception:                            # noqa: BLE001
            ch_ok = False
        inc_ok = False
        for _try in range(2):                        # retry once: never let a
            try:                                     # transient error score 0
                inc_ok, _ = verify(t, ollama_chat(incumbent, t["prompt"]))
                break
            except Exception:                        # noqa: BLE001
                pass
        ch_pass += ch_ok
        inc_pass += inc_ok
        if ch_ok and not inc_ok:
            ch_wins += 1
        elif inc_ok and not ch_ok:
            inc_wins += 1
        records.append({"id": t["id"], "challenger": ch_ok, "incumbent": inc_ok})
        if i % 20 == 0:
            print(f"[gate] {i}/{len(tasks)}  ch {ch_pass}  inc {inc_pass}")

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
