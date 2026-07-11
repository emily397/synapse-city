"""Persistence. Dual backend:

  * DATABASE_URL set  -> Postgres (Neon) via psycopg 3   [cloud / shared / durable]
  * otherwise         -> local SQLite file               [local dev, zero setup]

Same method surface either way. Embeddings stored as raw float32 bytes
(BLOB / BYTEA).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

import numpy as np

from .config import CONFIG

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT, tick INTEGER, ts REAL, kind TEXT, text TEXT,
    importance INTEGER, embedding BLOB);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, ts REAL, district TEXT, kind TEXT, signal TEXT,
    topic TEXT, participants TEXT);
CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER, turn INTEGER, speaker TEXT, prompt TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS judgements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER, agent_a TEXT, agent_b TEXT,
    score_a REAL, score_b REAL, winner TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS generations (
    gen INTEGER PRIMARY KEY, ts REAL, sft_count INTEGER, dpo_count INTEGER,
    trained INTEGER DEFAULT 0, promoted INTEGER DEFAULT 0, winrate REAL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS elo (model TEXT PRIMARY KEY, rating REAL, games INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS eval_runs (
    gen INTEGER PRIMARY KEY, ts REAL, passed INTEGER, total INTEGER, rate REAL, model TEXT);
"""

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id SERIAL PRIMARY KEY, agent TEXT, tick INTEGER, ts DOUBLE PRECISION, kind TEXT,
    text TEXT, importance INTEGER, embedding BYTEA);
CREATE TABLE IF NOT EXISTS interactions (
    id SERIAL PRIMARY KEY, tick INTEGER, ts DOUBLE PRECISION, district TEXT, kind TEXT,
    signal TEXT, topic TEXT, participants TEXT);
CREATE TABLE IF NOT EXISTS exchanges (
    id SERIAL PRIMARY KEY, interaction_id INTEGER, turn INTEGER, speaker TEXT,
    prompt TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS judgements (
    id SERIAL PRIMARY KEY, interaction_id INTEGER, agent_a TEXT, agent_b TEXT,
    score_a DOUBLE PRECISION, score_b DOUBLE PRECISION, winner TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS generations (
    gen INTEGER PRIMARY KEY, ts DOUBLE PRECISION, sft_count INTEGER, dpo_count INTEGER,
    trained INTEGER DEFAULT 0, promoted INTEGER DEFAULT 0, winrate DOUBLE PRECISION DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS elo (model TEXT PRIMARY KEY, rating DOUBLE PRECISION, games INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS eval_runs (
    gen INTEGER PRIMARY KEY, ts DOUBLE PRECISION, passed INTEGER, total INTEGER,
    rate DOUBLE PRECISION, model TEXT);
"""


class DB:
    def __init__(self, path=None):
        self.pg = bool(DATABASE_URL)
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
            with self.conn.cursor() as c:
                for stmt in _PG_SCHEMA.split(";"):
                    if stmt.strip():
                        c.execute(stmt)
        else:
            self.conn = sqlite3.connect(str(path or CONFIG.db_file))
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(_SQLITE_SCHEMA)
            self.conn.commit()

    # --- low-level helpers (unify sqlite/pg) ---
    def _q(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.pg else sql

    def _pg_exec(self, sql, params, fetch=None):
        # Neon suspends idle computes and drops the connection; reconnect once.
        import psycopg
        for attempt in (0, 1):
            try:
                with self.conn.cursor() as c:
                    c.execute(sql, params)
                    return c.fetchall() if fetch else None
            except (psycopg.OperationalError, psycopg.InterfaceError):
                if attempt:
                    raise
                from psycopg.rows import dict_row
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = psycopg.connect(DATABASE_URL, row_factory=dict_row,
                                            autocommit=True)

    def _all(self, sql, params=()) -> list[dict]:
        if self.pg:
            return self._pg_exec(self._q(sql), params, fetch=True)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def _one(self, sql, params=()):
        rows = self._all(sql, params)
        return rows[0] if rows else None

    def _run(self, sql, params=()):
        if self.pg:
            self._pg_exec(self._q(sql), params)
        else:
            self.conn.execute(sql, params)
            self.conn.commit()

    def _insert(self, sql, params) -> int:
        if self.pg:
            return self._pg_exec(self._q(sql) + " RETURNING id", params,
                                 fetch=True)[0]["id"]
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.lastrowid

    def _upsert(self, table, pk, cols, params):
        placeholders = ",".join(["?"] * len(cols))
        if self.pg:
            sets = ",".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
            self._run(f"INSERT INTO {table}({','.join(cols)}) VALUES({placeholders}) "
                      f"ON CONFLICT ({pk}) DO UPDATE SET {sets}", params)
        else:
            self._run(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({placeholders})", params)

    # --- memories ---
    def add_memory(self, agent, tick, kind, text, importance, emb: np.ndarray) -> int:
        return self._insert(
            "INSERT INTO memories(agent,tick,ts,kind,text,importance,embedding)"
            " VALUES(?,?,?,?,?,?,?)",
            (agent, tick, time.time(), kind, text, int(importance),
             emb.astype(np.float32).tobytes()))

    def memories_for(self, agent: str) -> list[dict]:
        rows = self._all("SELECT * FROM memories WHERE agent=? ORDER BY id", (agent,))
        for d in rows:
            d["vec"] = np.frombuffer(bytes(d["embedding"]), dtype=np.float32)
        return rows

    # --- interactions / exchanges / judgements ---
    def add_interaction(self, tick, district, kind, signal, topic, participants) -> int:
        return self._insert(
            "INSERT INTO interactions(tick,ts,district,kind,signal,topic,participants)"
            " VALUES(?,?,?,?,?,?,?)",
            (tick, time.time(), district, kind, signal, topic, json.dumps(participants)))

    def add_exchange(self, interaction_id, turn, speaker, prompt, response) -> None:
        self._run("INSERT INTO exchanges(interaction_id,turn,speaker,prompt,response)"
                  " VALUES(?,?,?,?,?)", (interaction_id, turn, speaker, prompt, response))

    def add_judgement(self, interaction_id, a, b, sa, sb, winner, reason) -> None:
        self._run(
            "INSERT INTO judgements(interaction_id,agent_a,agent_b,score_a,score_b,winner,reason)"
            " VALUES(?,?,?,?,?,?,?)", (interaction_id, a, b, sa, sb, winner, reason))

    # --- harvest queries ---
    def high_quality_exchanges(self, min_score: float) -> list[dict]:
        return self._all("""
            SELECT e.prompt, e.response, j.score_a, j.score_b, j.agent_a, j.agent_b, e.speaker
            FROM exchanges e JOIN judgements j ON e.interaction_id=j.interaction_id
            WHERE (e.speaker=j.agent_a AND j.score_a>=?)
               OR (e.speaker=j.agent_b AND j.score_b>=?)
        """, (min_score, min_score))

    def preference_pairs(self, margin: float) -> list[dict]:
        return self._all("""
            SELECT i.topic, j.agent_a, j.agent_b, j.score_a, j.score_b, j.winner, i.id AS iid
            FROM judgements j JOIN interactions i ON i.id=j.interaction_id
            WHERE ABS(j.score_a-j.score_b) >= ?
        """, (margin,))

    def exchanges_for(self, interaction_id: int) -> list[dict]:
        return self._all("SELECT * FROM exchanges WHERE interaction_id=? ORDER BY turn",
                         (interaction_id,))

    # --- generations / elo / eval ---
    def record_generation(self, gen, sft, dpo, note="") -> None:
        self._upsert("generations", "gen",
                     ["gen", "ts", "sft_count", "dpo_count", "note"],
                     (gen, time.time(), sft, dpo, note))

    def set_elo(self, model, rating, games) -> None:
        self._upsert("elo", "model", ["model", "rating", "games"], (model, rating, games))

    def get_elo(self) -> list[dict]:
        return self._all("SELECT * FROM elo ORDER BY rating DESC")

    def add_eval_run(self, gen, passed, total, rate, model) -> None:
        self._upsert("eval_runs", "gen",
                     ["gen", "ts", "passed", "total", "rate", "model"],
                     (gen, time.time(), passed, total, rate, model))

    def eval_history(self) -> list[dict]:
        return self._all("SELECT gen,passed,total,rate,model FROM eval_runs ORDER BY gen")

    def latest_eval(self) -> dict | None:
        return self._one("SELECT gen,passed,total,rate,model FROM eval_runs ORDER BY gen DESC LIMIT 1")

    def counts(self) -> dict:
        return {
            "memories": self._one("SELECT COUNT(*) AS n FROM memories")["n"],
            "interactions": self._one("SELECT COUNT(*) AS n FROM interactions")["n"],
            "exchanges": self._one("SELECT COUNT(*) AS n FROM exchanges")["n"],
            "judgements": self._one("SELECT COUNT(*) AS n FROM judgements")["n"],
        }
