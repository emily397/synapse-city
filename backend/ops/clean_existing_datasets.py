"""One-time migration: re-clean every already-harvested SFT/DPO target with the
new correctness-preserving cleaner, so the FULL accumulated corpus that
with_replay() loads is verifier-shaped (no `# Example usage`/print noise). The
cleaner was proven to preserve pass/fail on 400/400 real attempts. Idempotent.
"""
import glob
import json
import os
import sys

sys.path.insert(0, r"C:\synapse-city\backend")
from synapse.harvest import clean_task_target  # noqa: E402

DS = r"C:\synapse-city\backend\run\datasets"


def clean_sft_file(path: str) -> int:
    changed = 0
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        msgs = r.get("messages")
        if msgs:
            for m in msgs:
                if m.get("role") == "assistant":
                    new = clean_task_target(m.get("content", ""))
                    if new != m.get("content"):
                        m["content"] = new
                        changed += 1
        rows.append(r)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return changed


def clean_dpo_file(path: str) -> int:
    changed = 0
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if "chosen" in r:
            new = clean_task_target(r["chosen"])
            if new != r["chosen"]:
                r["chosen"] = new
                changed += 1
        rows.append(r)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return changed


def main():
    sft = glob.glob(os.path.join(DS, "gen*_sft*.jsonl"))
    dpo = glob.glob(os.path.join(DS, "gen*_dpo*.jsonl"))
    tot_sft = tot_dpo = 0
    for p in sft:
        tot_sft += clean_sft_file(p)
    for p in dpo:
        tot_dpo += clean_dpo_file(p)
    print(f"cleaned {len(sft)} SFT files ({tot_sft} targets rewritten), "
          f"{len(dpo)} DPO files ({tot_dpo} chosen rewritten)")


if __name__ == "__main__":
    main()
