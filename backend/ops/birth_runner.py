"""Birth runner (GPU side). The sim decides WHO reproduces — emergently, from
real bonds (synapse/simulation._family_life). This executes the biology for each
CONCEIVED couple: average the two parents' LoRA adapters into a genuine child
model (model soup), register it in Ollama, and spawn the newborn into the live
town with a lineage record. Run when the GPU is free (the supervisor calls it).

    python birth_runner.py            # process all pending conceptions
"""
from __future__ import annotations

import os
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "training"))
from train_cycle import BASE_MAP                          # noqa: E402

DB = ROOT / "run" / "synapse.db"
ADAPTERS = ROOT / "run" / "adapters"
LOCK = Path(os.getenv("SYNAPSE_TRAINING_LOCK",
                      r"C:\Users\nirvana\.synapse\TRAINING.lock"))
BACKEND = "http://127.0.0.1:8000"

# newborn names — nature/foundling flavoured, distinct from the founders
CHILD_NAMES = ["Sable", "Ash", "Fen", "Bryn", "Cove", "Dell", "Esme", "Flint",
               "Gale", "Hollis", "Iris", "Juno", "Kestrel", "Lark", "Marlow",
               "Neve", "Perrin", "Quill", "Rowan", "Sage", "Thorn", "Vesper",
               "Wilder", "Yarrow", "Bo", "Clover", "Wren-son", "Ember"]


def latest_adapter(rid: str) -> Path | None:
    d = ADAPTERS / rid
    if not d.is_dir():
        return None
    cands = [s for s in d.iterdir()
             if s.is_dir() and s.name.startswith("gen")
             and (s / "adapter_model.safetensors").exists()]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def wsl(p: Path) -> str:
    s = str(p).replace("\\", "/")
    return "/mnt/c/" + s[3:] if s[1:3] == ":/" else s


def find_modelfile(a: str, tag: str) -> Path | None:
    root = ADAPTERS / a
    if not root.exists():
        return None
    hits = [m for m in root.rglob("Modelfile") if tag in str(m)]
    return sorted(hits, key=lambda p: p.stat().st_mtime)[-1] if hits else None


def blend(pa: dict, pb: dict, name: str, tag: str) -> dict:
    """A NewResident body: build_persona fills the rest. The child echoes both
    parents in home, colour and voice."""
    return {
        "name": name, "model": tag,
        "role": f"child of {pa['name']} and {pb['name']}",
        "color": pa.get("color") or "#cccccc",
        "home": pa.get("home", "plaza"),
        "body": "sphere", "hat": "none",
        "voice": (f"Young and searching; carries {pa['name']}'s "
                  f"{(pa.get('traits') or ['way'])[0]} and {pb['name']}'s "
                  f"{(pb.get('traits') or ['way'])[0]}"),
        "goal": "find out who they are, apart from where they came from",
        "is_judge": False,
    }


def main():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    births = [dict(r) for r in
              con.execute("SELECT * FROM expecting WHERE status='conceived'")]
    if not births:
        print("no pending conceptions")
        return
    row = con.execute("SELECT v FROM simstate WHERE k='day'").fetchone()
    day = int(row["v"]) if row else 1
    personas = {a["id"]: a for a in
                httpx.get(f"{BACKEND}/api/agents", timeout=20).json()}
    existing_ids = set(personas)
    rng = random.Random(int(time.time()))

    for bd in births:
        a, b, model = bd["a"], bd["b"], bd["base"]
        aa, ba = latest_adapter(a), latest_adapter(b)
        if not (aa and ba):
            print(f"[skip] {a}+{b}: a parent has no genes (adapter) yet")
            continue
        hf = BASE_MAP.get(model)
        if not hf:
            print(f"[skip] {a}+{b}: no HF base mapping for {model}")
            continue
        nkids = con.execute(
            "SELECT COUNT(*) c FROM families WHERE (parent_a=? AND parent_b=?)"
            " OR (parent_a=? AND parent_b=?)", (a, b, b, a)).fetchone()["c"]
        tag = f"child-{a}-{b}-gen{nkids + 1}"
        name = next((n for n in rng.sample(CHILD_NAMES, len(CHILD_NAMES))
                     if n.lower() not in existing_ids), f"Child{rng.randint(10, 99)}")

        print(f"=== conceiving {name}: {a} x {b} on {model} ===")
        LOCK.write_text(f"birth {a}+{b} {time.strftime('%Y-%m-%dT%H:%M:%S')}")
        time.sleep(4)                                   # let the town rest
        bash = (
            "cd /mnt/c/synapse-city/backend/training && "
            "SYNAPSE_OLLAMA_URL=http://$(ip route show default | awk '{print $3}'):11434 "
            "/root/proprietary-model/.venv/bin/python reproduce.py "
            f"--base '{hf}' --adapter-a '{wsl(aa)}' --adapter-b '{wsl(ba)}' "
            f"--child-tag '{tag}' --name '{name}'")
        r = subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "--", "bash", "-c", bash],
                           capture_output=True, text=True)
        print(r.stdout[-1200:])
        if r.stderr:
            print("[stderr]", r.stderr[-400:])

        mf = find_modelfile(a, tag)
        if not mf:
            print(f"[fail] {name}: no child GGUF produced (fusion failed) — leaving "
                  f"conception pending to retry")
            continue
        subprocess.run(["ollama", "create", tag, "-f", str(mf)],
                       cwd=str(mf.parent), check=False)
        tags = httpx.get("http://localhost:11434/api/tags", timeout=20).json()
        names = [m["name"] for m in tags.get("models", [])]
        if not any(t == tag or t == f"{tag}:latest" for t in names):
            print(f"[fail] {name}: ollama create did not register {tag}")
            continue

        body = blend(personas.get(a, {"name": a}), personas.get(b, {"name": b}), name, tag)
        try:
            resp = httpx.post(f"{BACKEND}/api/agents", json=body, timeout=30)
            child_public = resp.json()
            child_id = child_public.get("id", name.lower())
        except Exception as e:                          # noqa: BLE001
            print(f"[warn] spawn POST failed ({e}); child model exists, will appear on restart")
            child_id = name.lower()
        con.execute(
            "INSERT OR REPLACE INTO families(child,parent_a,parent_b,born_day)"
            " VALUES(?,?,?,?)", (child_id, a, b, day))
        con.execute("UPDATE expecting SET status='born' WHERE pair=?", (bd["pair"],))
        con.commit()
        print(f"[BORN] {name} ({tag}) — child of {a} and {b} — walks into town")

    con.close()
    LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
