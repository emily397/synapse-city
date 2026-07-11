"""Build a frozen, versioned held-out eval suite.

    python -m evalsuite.build_suite --version 1

Emits evalsuite/suite_v<N>.jsonl: 16 families x 10 reserved eval seeds = 160
tasks. Seeds start at EVAL_SEED_BASE (1_000_000); training generators must stay
below that, so the suite is held out by construction. Commit the file; never
edit a published version — bump the version instead.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .families import EVAL_SEED_BASE, FAMILIES, make_task

HERE = Path(__file__).resolve().parent
PER_FAMILY = 10


def main(version: int):
    out = HERE / f"suite_v{version}.jsonl"
    if out.exists():
        raise SystemExit(f"{out.name} already exists — suites are frozen; bump the version.")
    tasks = [make_task(fam, EVAL_SEED_BASE + i)
             for fam in sorted(FAMILIES) for i in range(PER_FAMILY)]
    with out.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    kinds = {}
    for t in tasks:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    print(f"wrote {len(tasks)} tasks -> {out}  ({kinds})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=1)
    main(ap.parse_args().version)
