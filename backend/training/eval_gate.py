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

import httpx

from common import BASE_MODEL, MAX_SEQ, ADAPTERS, RUN

OLLAMA = "http://localhost:11434"
JUDGE_MODEL = "qwen2.5:7b-instruct"
PROMOTE_MIN_WINRATE = 0.55

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


def main(gen: int, which: str, incumbent: str):
    from unsloth import FastLanguageModel
    adapter = ADAPTERS / f"gen{gen}-{which}"
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(adapter), max_seq_length=MAX_SEQ, load_in_4bit=True)
    FastLanguageModel.for_inference(model)

    def challenger_gen(prompt: str) -> str:
        msgs = [{"role": "user", "content": prompt}]
        ids = tokenizer.apply_chat_template(msgs, return_tensors="pt",
                                            add_generation_prompt=True).to(model.device)
        out = model.generate(input_ids=ids, max_new_tokens=220, temperature=0.7,
                             do_sample=True)
        return tokenizer.decode(out[0][ids.shape[1]:], skip_special_tokens=True).strip()

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--adapter", choices=["sft", "dpo"], default="dpo")
    ap.add_argument("--incumbent", default="qwen2.5:7b-instruct")
    a = ap.parse_args()
    raise SystemExit(0 if main(a.gen, a.adapter, a.incumbent) else 1)
