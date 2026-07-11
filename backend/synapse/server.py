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
