"""Objective self-eval: a held-out set of tasks with CODE verifiers (no LLM
judge, so the metric cannot be reward-hacked). Run against the town's current
chat model each generation to get a second, honest quality axis alongside the
per-agent debate ELO. Answers are checked leniently (extract the answer from
free text) so a correct model passes even when it adds chatter.

Under the mock brain this scores near zero (the offline brain does not reason);
that is honest. Under a real Ollama model it moves as SFT/DPO improve reasoning
and instruction-following.
"""
from __future__ import annotations

import json
import re

from . import llm
from .config import CONFIG


def _first_int(s: str):
    m = re.search(r"-?\d+", s.replace(",", ""))
    return int(m.group()) if m else None


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def _v_three_primes(s: str) -> bool:
    nums = [int(x) for x in re.findall(r"\d+", s)]
    return len(nums) >= 3 and all(_is_prime(n) for n in nums[:3]) and len(set(nums[:3])) == 3


def _v_json_ab(s: str) -> bool:
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return False
    try:
        o = json.loads(m.group())
        return o.get("a") == 1 and o.get("b") == 2
    except Exception:
        return False


# id, prompt, verify(response)->bool
TASKS = [
    ("add",     "What is 17 + 25? Reply with only the number.",
     lambda r: _first_int(r) == 42),
    ("speed",   "A train travels 60 km in 30 minutes. Speed in km/h? Number only.",
     lambda r: _first_int(r) == 120),
    ("count",   "How many letters are in the word 'strawberry'? Number only.",
     lambda r: _first_int(r) == 10),
    ("seq",     "Continue: 2, 4, 8, 16, ? Reply with only the next number.",
     lambda r: _first_int(r) == 32),
    ("primes",  "List exactly three different prime numbers, comma-separated.",
     _v_three_primes),
    ("json",    'Reply with a JSON object with keys "a" and "b" set to 1 and 2.',
     _v_json_ab),
    ("exact",   "Reply with exactly the word BANANA in uppercase and nothing else.",
     lambda r: r.strip().upper().strip(".!\"'") == "BANANA"),
    ("reverse", "Reverse the string 'abc'. Reply with only the result.",
     lambda r: "cba" in r.lower()),
]


async def run_eval() -> dict:
    per = {}
    passed = 0
    for tid, prompt, verify in TASKS:
        try:
            out = await llm.chat(
                [{"role": "system", "content": "You answer concisely and follow the format exactly."},
                 {"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=40)
            ok = bool(verify(out))
        except Exception:
            ok, out = False, ""
        per[tid] = {"ok": ok, "answer": out[:80]}
        passed += int(ok)
    total = len(TASKS)
    return {"passed": passed, "total": total,
            "rate": round(passed / total, 3), "per_task": per,
            "model": CONFIG.chat_model}
