"""One full self-improvement generation on the GPU box:

    SFT  ->  DPO  ->  eval-gate  ->  (if it wins) export to Ollama + promote

    python train_cycle.py --gen 3 --incumbent qwen2.5:7b-instruct
    python train_cycle.py --gen 3 --resident forge      # PERSONAL LoRA

Safe by construction: nothing reaches the live town unless eval_gate PROMOTES it.
Per-resident runs train the resident's OWN base model on ONLY its own verified
rows and promote to a personal tag (e.g. forge-gen3). Schedule nightly while the
town is paused (ops/gpu_handover.ps1) so the single 3090 isn't serving and
training at full tilt simultaneously.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASETS = HERE.parent / "run" / "datasets"
PERSONAS = HERE.parent / "data" / "personas.json"

MIN_RESIDENT_ROWS = 100      # never train a personal LoRA on noise

# Ollama serving tag -> HF 4-bit base for Unsloth. Personal LoRAs train on the
# resident's OWN base family, not the town default.
BASE_MAP = {
    "qwen2.5:7b-instruct": "unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
    "qwen2.5:14b": "unsloth/Qwen2.5-14B-Instruct-bnb-4bit",
    "llama3.2:3b": "unsloth/Llama-3.2-3B-Instruct-bnb-4bit",
    "phi4:14b": "unsloth/phi-4-bnb-4bit",
    "hermes3:8b": "unsloth/Hermes-3-Llama-3.1-8B-bnb-4bit",
    "qwen2.5-coder:7b": "unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit",
    "qwen2.5:3b-instruct": "unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
    "qwen2.5:0.5b": "unsloth/Qwen2.5-0.5B-Instruct-bnb-4bit",  # Sol, the learner
    "gemma3:12b": "unsloth/gemma-3-12b-it-bnb-4bit",
    # aya-expanse (Cohere) — best-effort base; if Unsloth can't load this arch the
    # cycle logs a load error rather than silently skipping (see gate check).
    "aya-expanse:8b": "unsloth/aya-expanse-8b",
    # nucbox customs: customised from these bases (adjust if yours differ)
    "nucbox-reasoning:latest": "unsloth/DeepSeek-R1-Distill-Qwen-14B-bnb-4bit",
    "nucbox-coder:latest": "unsloth/Qwen2.5-Coder-14B-Instruct-bnb-4bit",
}


def run(script: str, *args: str, env: dict | None = None) -> int:
    print(f"\n=== {script} {' '.join(args)} ===")
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([sys.executable, str(HERE / script), *args], env=e).returncode


def _resident_env(resident: str) -> dict | None:
    """Resolve env for a per-resident run: its own base model + dataset suffix.
    Returns None (skip) if the resident lacks enough fresh rows."""
    personas = json.loads(PERSONAS.read_text(encoding="utf-8"))["agents"]
    p = next((x for x in personas if x["id"] == resident), None)
    if p is None:
        sys.exit(f"unknown resident '{resident}'")
    tag = p.get("model") or "qwen2.5:7b-instruct"
    base = BASE_MAP.get(tag)
    if base is None:
        sys.exit(f"no HF base mapping for {tag}; add it to BASE_MAP")
    rows = 0
    for f in DATASETS.glob(f"gen*_sft_{resident}.jsonl"):
        rows += sum(1 for l in f.read_text(encoding="utf-8").splitlines() if l.strip())
    if rows < MIN_RESIDENT_ROWS:
        print(f"[skip] {resident}: only {rows} personal SFT rows "
              f"(< {MIN_RESIDENT_ROWS}); not training on noise.")
        return None
    print(f"[resident] {resident}: base={base}, personal rows={rows}")
    return {"SYNAPSE_RESIDENT": resident, "SYNAPSE_BASE_MODEL": base}


def main(gen: int, incumbent: str, resident: str | None = None):
    g = str(gen)
    env = None
    tag = f"synapse-gen{gen}"
    if resident:
        env = _resident_env(resident)
        if env is None:
            return
        personas = json.loads(PERSONAS.read_text(encoding="utf-8"))["agents"]
        incumbent = next(x["model"] for x in personas if x["id"] == resident)
        tag = f"{resident}-gen{gen}"
    # Epochs scale to base strength. Tiny/weak learners (0.5B-1.5B) have real
    # headroom and need MORE passes to actually absorb the curriculum (Sol tied
    # her base at 1 epoch — learned some, forgot some). Strong instruct bases
    # (7B+) overfit fast, so they stay at a single gentle pass.
    tagl = (incumbent or "").lower()
    epochs = "3" if any(s in tagl for s in ("0.5b", "1.5b")) else "1"
    if run("train_lora.py", "--gen", g, "--epochs", epochs, env=env) != 0:
        sys.exit("SFT failed")
    # DPO is OPTIONAL: many residents have no judged Arena pairs yet (and none of
    # the execution-verified correct-vs-incorrect kind). Missing preference data
    # must NOT kill the cycle — we gate the SFT adapter, which is already genuine
    # learning. Only residents WITH pairs get the extra DPO polish.
    adapter = "dpo" if run("train_dpo.py", "--gen", g, "--from-sft", env=env) == 0 \
        else "sft"
    if adapter == "sft":
        print("[warn] no DPO pairs (or DPO failed); gating the SFT adapter.")
    if run("eval_gate.py", "--gen", g, "--adapter", adapter, "--incumbent", incumbent,
           "--suite", "suite_v1.jsonl", env=env) == 0:
        run("export_gguf.py", "--gen", g, "--adapter", adapter, "--tag", tag, env=env)
        print(f"\n✅ {tag} PROMOTED over {incumbent}.")
        if resident:
            # close the loop: the resident's brain is swapped automatically;
            # the supervisor's next backend restart serves the new self
            data = json.loads(PERSONAS.read_text(encoding="utf-8"))
            for p in data["agents"]:
                if p["id"] == resident:
                    p["model"] = tag
            PERSONAS.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"   personas.json updated: {resident} now runs {tag}.")
        else:
            print(f"   set SYNAPSE_CHAT_MODEL={tag} and restart the orchestrator.")
    else:
        print(f"\n🛑 {tag} REJECTED by eval-gate vs {incumbent}. "
              f"Town keeps the incumbent; more/better data next round.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--incumbent", default="qwen2.5:7b-instruct")
    ap.add_argument("--resident", default=None,
                    help="train a PERSONAL LoRA for this resident id on its own "
                         "data and base model (e.g. --resident forge)")
    a = ap.parse_args()
    main(a.gen, a.incumbent, a.resident)
