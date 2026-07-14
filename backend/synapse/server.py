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


# --- god-mode one-off world events (frontend buttons) --------------------- #
# Each shoves the shared world once; the consequence cascade plays out the
# aftermath over following days. All are non-blocking and can't break the sim.
def _god(fn_name: str):
    ids = list(SIM.agents)
    fn = getattr(SIM.consequences, fn_name)
    ev = fn(SIM.survival, ids, SIM.rng)
    asyncio.create_task(_broadcast_memory(ev))
    return {"event": fn_name, "env": SIM.consequences.state()}


@app.post("/api/flood")
async def flood():
    """A flood: waters rise, stores soak, low fields drown. One-off."""
    return _god("flood")


@app.post("/api/fire")
async def fire():
    """A wildfire: the woods and town-edge burn; timber and forage lost. One-off."""
    return _god("wildfire")


@app.post("/api/harvest")
async def harvest_boon():
    """A bountiful harvest: full stores, cheap food, soaring spirits. One-off."""
    return _god("bounty_harvest")


@app.post("/api/trees")
async def trees():
    """A gift of trees: a new grove for timber and forage. One-off."""
    return _god("gift_trees")


@app.post("/api/rain")
async def rain():
    """A gentle rain: wells fill, soil recovers, gardens grow again. One-off."""
    return _god("gift_rain")


@app.post("/api/knowledge")
async def knowledge():
    """A gift of knowledge: fresh notes appear in the Town Library to study and
    argue over. One-off."""
    notes = [
        ("science", "Small, steady improvements compound: a system that learns a "
         "little every day outruns one that waits for a great leap.", "a gift of knowledge"),
        ("craft", "Rotate the fields and let some rest, or the soil gives less each "
         "year - abundance now can beget scarcity later.", "a gift of knowledge"),
        ("reason", "When two people disagree, the fastest path to truth is to state "
         "what evidence would change your own mind.", "a gift of knowledge"),
        ("engineering", "Store water when it is plentiful; the cheapest well is the "
         "rain you kept from yesterday.", "a gift of knowledge"),
        ("philosophy", "A community is stronger when the strongest teach what they "
         "know to the ones who struggle most.", "a gift of knowledge"),
    ]
    day = SIM.day

    async def _add():
        for kind, claim, src in notes:
            try:
                await SIM.library.add_note(kind, claim, src, day)
            except Exception:
                pass

    asyncio.create_task(_add())
    asyncio.create_task(_broadcast_memory(
        "A trove of new knowledge arrived in the Town Library - fresh ideas to "
        "study, teach, and argue over."))
    return {"event": "knowledge", "notes_added": len(notes)}


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
