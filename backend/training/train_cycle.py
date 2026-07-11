"""One full self-improvement generation on the GPU box:

    SFT  ->  DPO  ->  eval-gate  ->  (if it wins) export to Ollama + promote

    python train_cycle.py --gen 3 --incumbent qwen2.5:7b-instruct

Safe by construction: nothing reaches the live town unless eval_gate PROMOTES it.
Schedule this nightly (Task Scheduler / cron) while the town is snapshotted, so
the single 3090 isn't serving and training at full tilt simultaneously.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str) -> int:
    print(f"\n=== {script} {' '.join(args)} ===")
    return subprocess.run([sys.executable, str(HERE / script), *args]).returncode


def main(gen: int, incumbent: str):
    g = str(gen)
    if run("train_lora.py", "--gen", g) != 0:
        sys.exit("SFT failed")
    if run("train_dpo.py", "--gen", g, "--from-sft") != 0:
        sys.exit("DPO failed")
    if run("eval_gate.py", "--gen", g, "--adapter", "dpo", "--incumbent", incumbent,
           "--suite", "suite_v1.jsonl") == 0:
        run("export_gguf.py", "--gen", g, "--adapter", "dpo")
        print(f"\n✅ gen{gen} PROMOTED. Point the town at synapse-gen{gen}:")
        print(f"   set SYNAPSE_CHAT_MODEL=synapse-gen{gen} and restart the orchestrator.")
    else:
        print(f"\n🛑 gen{gen} REJECTED by eval-gate. Town keeps the incumbent. "
              f"Loop continues; more/better debates next round.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--incumbent", default="qwen2.5:7b-instruct")
    a = ap.parse_args()
    main(a.gen, a.incumbent)
