"""Shared training helpers. GPU box only (imports unsloth/trl lazily in scripts)."""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "run"
DATASETS = RUN / "datasets"
ADAPTERS = RUN / "adapters"
ADAPTERS.mkdir(parents=True, exist_ok=True)

BASE_MODEL = os.getenv("SYNAPSE_BASE_MODEL", "unsloth/Qwen2.5-7B-Instruct-bnb-4bit")
MAX_SEQ = int(os.getenv("SYNAPSE_MAX_SEQ", "2048"))
REPLAY_FRACTION = float(os.getenv("SYNAPSE_REPLAY_FRACTION", "0.3"))


def load_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def with_replay(gen: int, suffix: str) -> list[dict]:
    """Anti-collapse anchor (SPIN pattern): current generation's data plus a
    replay sample of every prior generation, so the policy never drifts off the
    distribution that produced it."""
    cur = load_jsonl(DATASETS / f"gen{gen}_{suffix}.jsonl")
    prior = []
    for p in sorted(glob.glob(str(DATASETS / f"gen*_{suffix}.jsonl"))):
        g = int(Path(p).stem.split("_")[0][3:])
        if g < gen:
            prior += load_jsonl(p)
    if prior:
        keep = max(1, int(len(cur) * REPLAY_FRACTION))
        # deterministic slice; shuffle upstream if you want variety
        cur = cur + prior[:keep]
    return cur
