"""Runtime configuration. Env-overridable so the same code runs on the Nucbox
(mock brain, no GPU) and against the RTX 3090 (real Ollama) with no code change.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # backend/
DATA_DIR = ROOT / "data"
RUN_DIR = ROOT / "run"                                  # sqlite, snapshots, datasets, logs


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- brain backend ---
    # "mock"  -> deterministic offline brain (runs anywhere, great for the demo)
    # "ollama"-> real local models on the 3090
    llm_backend: str = os.getenv("SYNAPSE_LLM_BACKEND", "mock")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    chat_model: str = os.getenv("SYNAPSE_CHAT_MODEL", "qwen2.5:7b-instruct")
    judge_model: str = os.getenv("SYNAPSE_JUDGE_MODEL", "qwen2.5:7b-instruct")
    embed_model: str = os.getenv("SYNAPSE_EMBED_MODEL", "nomic-embed-text")
    max_tokens: int = int(os.getenv("SYNAPSE_MAX_TOKENS", "220"))
    temperature: float = float(os.getenv("SYNAPSE_TEMPERATURE", "0.8"))

    # --- simulation ---
    tick_seconds: float = float(os.getenv("SYNAPSE_TICK_SECONDS", "2.0"))
    minutes_per_tick: int = int(os.getenv("SYNAPSE_MINUTES_PER_TICK", "10"))
    conversation_turns: int = int(os.getenv("SYNAPSE_CONV_TURNS", "6"))
    harvest_interval: int = int(os.getenv("SYNAPSE_HARVEST_INTERVAL", "20"))  # ticks
    reflection_importance_threshold: int = 60   # sum of importances that triggers reflection
    night_start_hour: int = 22
    day_start_hour: int = 7
    seed: int = int(os.getenv("SYNAPSE_SEED", "1337"))

    # --- self-evolving world ---
    world_max_districts: int = int(os.getenv("SYNAPSE_MAX_DISTRICTS", "48"))
    world_expand_cooldown: int = int(os.getenv("SYNAPSE_EXPAND_COOLDOWN", "45"))   # ticks between gate openings
    world_curiosity: float = float(os.getenv("SYNAPSE_CURIOSITY", "0.10"))         # per idle agent, per tick, at a gate district

    # --- self-learning loop (Phase 2) ---
    harvest_min_score: float = 7.0              # SFT: keep exchanges the judge rates >= this /10
    dpo_margin: float = 2.0                     # DPO: min judge-score gap between chosen/rejected
    promote_min_winrate: float = 0.55           # eval gate: challenger must beat incumbent by this
    replay_fraction: float = 0.3                # fraction of each training set drawn from anchor/replay

    # --- paths ---
    personas_file: Path = DATA_DIR / "personas.json"
    world_file: Path = DATA_DIR / "world.json"
    db_file: Path = RUN_DIR / "synapse.db"

    def ensure_dirs(self) -> None:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / "datasets").mkdir(exist_ok=True)
        (RUN_DIR / "snapshots").mkdir(exist_ok=True)


CONFIG = Config()
CONFIG.ensure_dirs()
