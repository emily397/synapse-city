"""Voice-divergence metric: is per-resident growth actually producing distinct
residents, or are they converging into one voice?

Embeds each resident's last N utterances (Ollama embeddings), takes the
per-resident centroid, and logs the mean pairwise cosine DISTANCE between
centroids to run/REPORT.md. Rising = personalities diverging (personalisation
is real). Falling toward 0 = everyone sounds the same; flag it.

    python divergence.py            # uses the live SQLite db
Respects SYNAPSE_OLLAMA_URL. CPU-side; run weekly (or any time).
"""
from __future__ import annotations

import datetime
import itertools
import os
import sqlite3
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / "run"
DB = RUN / "synapse.db"
REPORT = RUN / "REPORT.md"
OLLAMA = os.getenv("SYNAPSE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.getenv("SYNAPSE_EMBED_MODEL", "nomic-embed-text")
N_UTTER = 200


def embed(text: str) -> np.ndarray | None:
    try:
        r = httpx.post(f"{OLLAMA}/api/embeddings",
                       json={"model": EMBED_MODEL, "prompt": text}, timeout=30)
        r.raise_for_status()
        v = np.asarray(r.json().get("embedding") or [], dtype=np.float32)
        if not v.size:
            return None
        n = np.linalg.norm(v)
        return v / n if n else v
    except Exception:
        return None


def main():
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    speakers = [r[0] for r in cur.execute(
        "SELECT DISTINCT speaker FROM exchanges").fetchall()]
    centroids: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    for s in speakers:
        rows = cur.execute(
            "SELECT response FROM exchanges WHERE speaker=? ORDER BY id DESC LIMIT ?",
            (s, N_UTTER)).fetchall()
        vecs = [v for (t,) in rows if t and (v := embed(t)) is not None]
        if len(vecs) >= 5:
            centroids[s] = np.mean(vecs, axis=0)
            counts[s] = len(vecs)
    con.close()

    if len(centroids) < 2:
        print("not enough residents with utterances yet")
        return

    dists = []
    for a, b in itertools.combinations(sorted(centroids), 2):
        ca, cb = centroids[a], centroids[b]
        cos = float(np.dot(ca, cb) / ((np.linalg.norm(ca) * np.linalg.norm(cb)) or 1.0))
        dists.append(1.0 - cos)
    mean_d = float(np.mean(dists))

    line = (f"- {datetime.datetime.now().isoformat(timespec='seconds')} :: "
            f"divergence | residents={len(centroids)} | "
            f"mean_pairwise_dist={mean_d:.4f} | "
            f"per_resident_utts={counts}")
    REPORT.parent.mkdir(exist_ok=True)
    if not REPORT.exists():
        REPORT.write_text("# Synapse City training report\n", encoding="utf-8")
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)
    if mean_d < 0.05:
        print("⚠ FLAG: residents are converging into one voice; "
              "personalisation is not real yet.")


if __name__ == "__main__":
    main()
