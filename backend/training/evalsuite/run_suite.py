"""Score a model (served by Ollama) on a frozen suite.

    python -m evalsuite.run_suite --model qwen2.5:7b-instruct --suite suite_v1.jsonl
    python -m evalsuite.run_suite --model qwen2.5:7b-instruct --limit 10   # smoke

Respects SYNAPSE_OLLAMA_URL (default http://localhost:11434) so the same code
runs from Windows (localhost) and WSL (Windows host IP). Writes per-task
results next to the suite as results_<model>_<suite>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx

from .verify import verify

HERE = Path(__file__).resolve().parent


def _resolve_ollama() -> str:
    """Where Ollama actually lives, robust to env-propagation failures. The
    in-handover gate kept getting a BROKEN SYNAPSE_OLLAMA_URL — empty, or
    'http://:11434' with no host (empty WINIP) — which made ollama_chat call a
    URL with no host -> 'missing protocol' -> incumbent 'unreachable' -> every
    autonomous cycle rejected against a phantom. So we only trust a WELL-FORMED
    http(s)://<host>[:port]; anything else falls through to detecting the Windows
    host from the WSL default gateway (Ollama runs on the Windows side)."""
    import re
    u = (os.getenv("SYNAPSE_OLLAMA_URL") or "").strip().rstrip("/")
    if re.match(r"^https?://[A-Za-z0-9._-]+(:\d+)?$", u):
        return u                                  # a real host:port — trust it
    try:                                          # empty / schemeless / no-host
        import subprocess
        parts = subprocess.run(["ip", "route", "show", "default"],
                               capture_output=True, text=True, timeout=5).stdout.split()
        if len(parts) >= 3 and parts[0] == "default":
            return f"http://{parts[2]}:11434"     # the Windows host from WSL
    except Exception:
        pass
    if u and "://" not in u:
        return "http://" + u                      # salvage a bare host:port
    return "http://localhost:11434"


OLLAMA = _resolve_ollama()

SYSTEM = ("You are a precise problem solver. For coding tasks reply with ONE "
          "```python code block defining the requested function. For other tasks, "
          "think briefly then end with the exact final line 'ANSWER: <value>'.")


def ollama_chat(model: str, prompt: str, timeout: float = 240.0) -> str:
    r = httpx.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False,
        "options": {"temperature": 0.0, "num_predict": 700},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()["message"]["content"]


def load_suite(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def score_model(model: str, tasks: list[dict], log=print) -> dict:
    results = []
    t0 = time.time()
    for i, t in enumerate(tasks, 1):
        try:
            out = ollama_chat(model, t["prompt"])
            ok, detail = verify(t, out)
        except Exception as e:                      # noqa: BLE001
            ok, detail, out = False, f"inference error: {e}", ""
        results.append({"id": t["id"], "family": t["family"], "pass": ok,
                        "detail": detail})
        log(f"[{i}/{len(tasks)}] {'PASS' if ok else 'fail'}  {t['id']}  {detail[:60]}")
    rate = sum(r["pass"] for r in results) / max(1, len(results))
    return {"model": model, "n": len(results), "rate": rate,
            "seconds": round(time.time() - t0, 1), "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--suite", default="suite_v1.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    tasks = load_suite(HERE / a.suite)
    if a.limit:
        tasks = tasks[:: max(1, len(tasks) // a.limit)][: a.limit]
    rep = score_model(a.model, tasks)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", a.model)
    out = HERE / f"results_{safe}_{Path(a.suite).stem}.json"
    out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"\n{a.model}: {rep['rate']:.1%} on {rep['n']} tasks "
          f"({rep['seconds']}s) -> {out.name}")


if __name__ == "__main__":
    main()
