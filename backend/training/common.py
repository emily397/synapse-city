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
# Per-resident growth: when set, all dataset paths get the resident suffix, so
# a resident's LoRA trains ONLY on its own verified rows.
RESIDENT = os.getenv("SYNAPSE_RESIDENT", "").strip()
if RESIDENT:
    # personal runs get their own adapter namespace: no clobbering between
    # residents, and each resident's lineage ("genes") stays intact
    ADAPTERS = RUN / "adapters" / RESIDENT
    ADAPTERS.mkdir(parents=True, exist_ok=True)


def _suffixed(suffix: str) -> str:
    return f"{suffix}_{RESIDENT}" if RESIDENT else suffix


def load_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def with_replay(gen: int, suffix: str) -> list[dict]:
    """Load the FULL accumulated corpus for this stream (all generations,
    deduplicated), honoring SYNAPSE_RESIDENT for personal runs.

    The harvest fragments data across many small gen*_ files; training on a
    single gen's sliver starves the run (it would finish in seconds on a few
    rows). Concatenating every generation and de-duping gives the resident its
    entire lived corpus, which is also the correct anti-collapse anchor: all
    prior data is always present, so the policy cannot drift off-distribution.
    The `gen` argument is kept for the filename/version, not to slice data."""
    base_suffix = suffix
    suffix = _suffixed(suffix)
    rows: list[dict] = []
    seen: set[str] = set()
    for p in sorted(glob.glob(str(DATASETS / f"gen*_{suffix}.jsonl"))):
        for r in load_jsonl(p):
            key = json.dumps(r, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                rows.append(r)
    if base_suffix == "sft":
        rows = _balance_sft(rows)
    return rows


def _is_task_row(r: dict) -> bool:
    """A row whose target is verifier-shaped (```python def solve / ANSWER:).
    These are the rows that actually move the eval-gate's task suite."""
    a = next((m.get("content", "") for m in (r.get("messages") or [])
              if m.get("role") == "assistant"), "")
    a = a.lstrip()
    return a.startswith("```python") or a.startswith("ANSWER:")


def _balance_sft(rows: list[dict],
                 max_conv_ratio: float = 0.4) -> list[dict]:
    """Keep execution-verified TASK rows dominant. Residents accumulate far more
    chit-chat than task attempts; unbalanced, conversation drowns the families
    the gate tests, so a personal LoRA can drift off the verifier's formats
    (quinn-gen8: 80% conversation/misc, collapsed on caesar/arith). We cap
    conversational rows so tasks stay the majority, while still keeping enough
    voice for the resident to sound like itself. Deterministic (stable anchor)."""
    tasks = [r for r in rows if _is_task_row(r)]
    conv = [r for r in rows if not _is_task_row(r)]
    if not tasks:
        return rows                          # no task fuel yet; keep everything
    cap = int(len(tasks) * (max_conv_ratio / (1.0 - max_conv_ratio)))
    return tasks + conv[:cap]
