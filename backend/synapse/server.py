"""FastAPI app: REST snapshot + WebSocket live feed. Boots the simulation on
startup and streams every world event to connected 3D clients.

Run:  uvicorn synapse.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import registry
from .bus import BUS
from .config import CONFIG
from .simulation import SIM

app = FastAPI(title="Synapse City")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

_sim_task: asyncio.Task | None = None


@app.on_event("startup")
async def _startup():
    global _sim_task
    _sim_task = asyncio.create_task(SIM.run())


@app.on_event("shutdown")
async def _shutdown():
    SIM.stop()
    if _sim_task:
        _sim_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _sim_task


@app.get("/api/state")
async def state():
    return JSONResponse(SIM.snapshot())


@app.get("/api/stats")
async def stats():
    return JSONResponse({"type": "stats", **SIM._stats(), "clock": SIM._clock()})


@app.get("/api/models")
async def models():
    """Models Ollama is serving + the districts a resident can live in."""
    return {
        "backend": CONFIG.llm_backend,
        "default": CONFIG.chat_model,
        "models": registry.list_ollama_models(),
        "districts": [{"id": d.id, "name": d.name}
                      for d in SIM.world.districts.values()],
        "bodies": ["capsule", "sphere", "box", "cone"],
        "hats": ["none", "antenna", "cap", "beanie", "crown", "halo"],
    }


@app.get("/api/agents")
async def agents():
    return [a.public() for a in SIM.agents.values()]


@app.get("/api/agents/{aid}/profile")
async def agent_profile(aid: str):
    """Everything the town knows about one resident: identity, debate record,
    memory growth, and its most recent thoughts — the check-in window on a
    model's autonomous development."""
    agent = SIM.agents.get(aid)
    if not agent:
        raise HTTPException(status_code=404, detail=f"no resident '{aid}'")
    db = SIM.db

    elo = db._one("SELECT rating, games FROM elo WHERE model=?", (aid,)) or {}
    wins = db._one(
        "SELECT count(*) AS n FROM judgements "
        "WHERE (agent_a=? AND winner='a') OR (agent_b=? AND winner='b')",
        (aid, aid)) or {}
    losses = db._one(
        "SELECT count(*) AS n FROM judgements "
        "WHERE (agent_a=? AND winner='b') OR (agent_b=? AND winner='a')",
        (aid, aid)) or {}
    mem_total = db._one(
        "SELECT count(*) AS n FROM memories WHERE agent=?", (aid,)) or {}
    mem_kinds = db._all(
        "SELECT kind, count(*) AS n FROM memories WHERE agent=? GROUP BY kind",
        (aid,))
    recent_memories = db._all(
        "SELECT kind, text, tick FROM memories WHERE agent=? "
        "ORDER BY id DESC LIMIT 6", (aid,))
    utterances = db._all(
        "SELECT e.response AS text, i.district, i.topic FROM exchanges e "
        "LEFT JOIN interactions i ON e.interaction_id = i.id "
        "WHERE e.speaker=? ORDER BY e.id DESC LIMIT 8", (aid,))
    spoken = db._one(
        "SELECT count(*) AS n FROM exchanges WHERE speaker=?", (aid,)) or {}
    convos = db._one(
        "SELECT count(*) AS n FROM interactions WHERE participants LIKE ?",
        (f"%{aid}%",)) or {}

    return {
        "agent": agent.public(),
        "elo": {"rating": elo.get("rating", 1000.0), "games": elo.get("games", 0)},
        "debates": {"wins": wins.get("n", 0), "losses": losses.get("n", 0)},
        "memories": {"total": mem_total.get("n", 0),
                     "by_kind": {r["kind"]: r["n"] for r in mem_kinds}},
        "recent_memories": recent_memories,
        "recent_utterances": utterances,
        "spoken_turns": spoken.get("n", 0),
        "conversations": convos.get("n", 0),
    }


class NewResident(BaseModel):
    name: str
    model: str = ""
    role: str = "Resident"
    color: str | None = None
    home: str = "plaza"
    body: str | None = None
    hat: str | None = None
    voice: str | None = None
    goal: str | None = None
    is_judge: bool = False


@app.post("/api/agents")
async def add_agent(body: NewResident):
    """Add a self-hosted model to the town as a resident with an avatar body."""
    spec = body.model_dump()
    spec["avatar"] = {"body": spec.pop("body"), "hat": spec.pop("hat")}
    persona = registry.build_persona(spec)
    try:
        public = SIM.add_agent(persona)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    registry.save_persona(persona)          # persist so it survives a restart
    return public


@app.post("/api/bounty")
async def bounty(amount: int = 45):
    """Divine intervention: a one-off communal food windfall appears in the
    square. Watch how the residents decide to divide and consume it; it does
    not renew."""
    ev = SIM.survival.grant_bounty(amount)
    # observe in the background so the request returns instantly (embedding all
    # residents' memories synchronously would block for many seconds)
    asyncio.create_task(_broadcast_memory(ev))
    return {"granted": amount, "bounty_now": SIM.survival.bounty()}


async def _broadcast_memory(text: str):
    for a in SIM.agents.values():
        try:
            await a.mem.observe(text, SIM.tick, kind="survival")
        except Exception:
            pass


@app.post("/api/omen")
async def omen():
    """A strange light crosses the sky and vanishes. Every resident witnesses
    it and will debate its meaning for days. One-off."""
    ev = SIM.survival.sky_omen(SIM.rng)
    asyncio.create_task(_broadcast_memory(ev))
    return {"omen": "seen", "talk_until_tick": SIM.survival.omen_until}


@app.post("/api/drought")
async def drought(ticks: int = 120):
    """Natural disaster: a sustained drought that kills most standing crops now
    and keeps new plantings from taking root for its duration. Temporary — it
    breaks on its own. Watch how they ration, trade, and fight to survive it."""
    ev = SIM.survival.start_drought(SIM.tick, ticks, SIM.agents)
    asyncio.create_task(_broadcast_memory(ev))
    return {"drought_ticks": ticks, "breaks_at_tick": SIM.survival.drought_until}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    q = BUS.subscribe()
    try:
        await sock.send_json(SIM.snapshot())          # instant paint
        for ev in BUS.recent():                        # replay recent motion
            await sock.send_json(ev)
        while True:
            ev = await q.get()
            await sock.send_json(ev)
    except WebSocketDisconnect:
        pass
    finally:
        BUS.unsubscribe(q)
