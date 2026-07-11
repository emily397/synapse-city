"""SQLite persistence. Thin, synchronous (calls are tiny; run under the sim loop).
Embeddings stored as raw float32 blobs."""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import numpy as np

from .config import CONFIG

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT, tick INTEGER, ts REAL,
    kind TEXT,                 -- observation | reflection | plan | dialogue
    text TEXT, importance INTEGER,
    embedding BLOB
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, ts REAL, district TEXT, kind TEXT,
    signal TEXT, topic TEXT, participants TEXT
);
CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER, turn INTEGER,
    speaker TEXT, prompt TEXT, response TEXT
);
CREATE TABLE IF NOT EXISTS judgements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER, agent_a TEXT, agent_b TEXT,
    score_a REAL, score_b REAL, winner TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS generations (
    gen INTEGER PRIMARY KEY,
    ts REAL, sft_count INTEGER, dpo_count INTEGER,
    trained INTEGER DEFAULT 0, promoted INTEGER DEFAULT 0,
    winrate REAL DEFAULT 0, note TEXT
);
CREATE TABLE IF NOT EXISTS elo (
    model TEXT PRIMARY KEY, rating REAL, games INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS eval_runs (
    gen INTEGER PRIMARY KEY, ts REAL,
    passed INTEGER, total INTEGER, rate REAL, model TEXT
);
"""


class DB:
    def __init__(self, path=None):
        self.conn = sqlite3.connect(str(path or CONFIG.db_file))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # --- memories ---
    def add_memory(self, agent, tick, kind, text, importance, emb: np.ndarray) -> int:
        cur = self.conn.execute(
            "INSERT INTO memories(agent,tick,ts,kind,text,importance,embedding)"
            " VALUES(?,?,?,?,?,?,?)",
            (agent, tick, time.time(), kind, text, int(importance),
             emb.astype(np.float32).tobytes()))
        self.conn.commit()
        return cur.lastrowid

    def memories_for(self, agent: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE agent=? ORDER BY id", (agent,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["vec"] = np.frombuffer(r["embedding"], dtype=np.float32)
            out.append(d)
        return out

    # --- interactions / exchanges / judgements ---
    def add_interaction(self, tick, district, kind, signal, topic, participants) -> int:
        cur = self.conn.execute(
            "INSERT INTO interactions(tick,ts,district,kind,signal,topic,participants)"
            " VALUES(?,?,?,?,?,?,?)",
            (tick, time.time(), district, kind, signal, topic, json.dumps(participants)))
        self.conn.commit()
        return cur.lastrowid

    def add_exchange(self, interaction_id, turn, speaker, prompt, response) -> None:
        self.conn.execute(
            "INSERT INTO exchanges(interaction_id,turn,speaker,prompt,response)"
            " VALUES(?,?,?,?,?)", (interaction_id, turn, speaker, prompt, response))
        self.conn.commit()

    def add_judgement(self, interaction_id, a, b, sa, sb, winner, reason) -> None:
        self.conn.execute(
            "INSERT INTO judgements(interaction_id,agent_a,agent_b,score_a,score_b,winner,reason)"
            " VALUES(?,?,?,?,?,?,?)", (interaction_id, a, b, sa, sb, winner, reason))
        self.conn.commit()

    # --- harvest queries (Phase 2) ---
    def high_quality_exchanges(self, min_score: float) -> list[dict]:
        rows = self.conn.execute("""
            SELECT e.prompt, e.response, j.score_a, j.score_b, j.agent_a, j.agent_b, e.speaker
            FROM exchanges e JOIN judgements j ON e.interaction_id=j.interaction_id
            WHERE (e.speaker=j.agent_a AND j.score_a>=?)
               OR (e.speaker=j.agent_b AND j.score_b>=?)
        """, (min_score, min_score)).fetchall()
        return [dict(r) for r in rows]

    def preference_pairs(self, margin: float) -> list[dict]:
        rows = self.conn.execute("""
            SELECT i.topic, j.agent_a, j.agent_b, j.score_a, j.score_b, j.winner, i.id AS iid
            FROM judgements j JOIN interactions i ON i.id=j.interaction_id
            WHERE ABS(j.score_a-j.score_b) >= ?
        """, (margin,)).fetchall()
        return [dict(r) for r in rows]

    def exchanges_for(self, interaction_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM exchanges WHERE interaction_id=? ORDER BY turn",
            (interaction_id,)).fetchall()
        return [dict(r) for r in rows]

    # --- generations / elo ---
    def record_generation(self, gen, sft, dpo, note="") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO generations(gen,ts,sft_count,dpo_count,note)"
            " VALUES(?,?,?,?,?)", (gen, time.time(), sft, dpo, note))
        self.conn.commit()

    def set_elo(self, model, rating, games) -> None:
        self.conn.execute("INSERT OR REPLACE INTO elo(model,rating,games) VALUES(?,?,?)",
                          (model, rating, games))
        self.conn.commit()

    def get_elo(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM elo ORDER BY rating DESC").fetchall()]

    def add_eval_run(self, gen, passed, total, rate, model) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO eval_runs(gen,ts,passed,total,rate,model)"
            " VALUES(?,?,?,?,?,?)", (gen, time.time(), passed, total, rate, model))
        self.conn.commit()

    def eval_history(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT gen,passed,total,rate,model FROM eval_runs ORDER BY gen").fetchall()]

    def latest_eval(self) -> dict | None:
        r = self.conn.execute(
            "SELECT gen,passed,total,rate,model FROM eval_runs ORDER BY gen DESC LIMIT 1"
        ).fetchone()
        return dict(r) if r else None

    def counts(self) -> dict:
        c = self.conn.execute
        return {
            "memories": c("SELECT COUNT(*) FROM memories").fetchone()[0],
            "interactions": c("SELECT COUNT(*) FROM interactions").fetchone()[0],
            "exchanges": c("SELECT COUNT(*) FROM exchanges").fetchone()[0],
            "judgements": c("SELECT COUNT(*) FROM judgements").fetchone()[0],
        }
