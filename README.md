# Synapse City

A living 3D suburb where your local open-source models live, talk, teach each other, and **measurably improve**, with no human in the loop. Built to run on the Nucbox + RTX 3090 and to look good enough to put in front of a client.

See [PLAN.md](PLAN.md) for the phased framework and the "why this actually trains" explanation.

```
                          ┌─────────────────────────────────────────┐
                          │            SYNAPSE CITY (3D)             │
   browser (r3f) ◀──WS──  │  agents walk districts, converse live    │
                          └───────────────┬─────────────────────────┘
                                          │ events
             Nucbox (CPU)   ┌─────────────▼─────────────┐
             orchestrator   │  sim loop · memory · judge │  SQLite
                            │  harvest -> SFT + DPO data │  run/datasets/*.jsonl
                            └─────────────┬─────────────┘
                                          │ nightly
             RTX 3090       ┌─────────────▼─────────────┐
             training       │ Unsloth QLoRA SFT -> DPO   │
                            │ eval-gate -> GGUF -> Ollama│  only promotes if it WINS
                            └─────────────┬─────────────┘
                                          │ hot-swap adapter
                                          ▼  loop repeats, town gets smarter
```

## What is real vs simulated (honest version)

- **Real, right now (mock brain, any machine):** the whole engine. Agents move, hold multi-turn conversations, remember each other, reflect at night, get judged in the Arena, and every exchange is harvested into real SFT + DPO JSONL. Per-agent **ELO is computed from actual debate outcomes**. The 3D city runs live.
- **Mock caveat:** with the offline brain the *dialogue text* is templated filler, so the harvested datasets have real structure but placeholder content. ELO and the loop mechanics are genuine.
- **Real training** happens when you point it at Ollama (real model text) and run the GPU training cycle. A new model version only reaches the town if it beats the incumbent at the eval-gate.

## Quick start (offline, no GPU, ~2 min)

Two terminals.

```bash
# 1) orchestrator (mock brain)
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn synapse.server:app --port 8000

# 2) the city
cd frontend
npm install
npm run dev            # open http://localhost:5173
```

The frontend also runs standalone (offline preview with a mock walker) if the backend is not up, so you can demo the visuals anywhere.

Headless engine test (no web, no GPU):

```bash
cd backend && python run_headless.py 200
```

## Going real (RTX 3090)

```bash
# on the 3090 box
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text

# point the orchestrator at Ollama
set SYNAPSE_LLM_BACKEND=ollama            # PowerShell: $env:SYNAPSE_LLM_BACKEND="ollama"
set SYNAPSE_CHAT_MODEL=qwen2.5:7b-instruct
uvicorn synapse.server:app --port 8000
```

Now the agents think with a real 7B model and the harvested datasets contain real reasoning and debate.

## The self-improvement cycle (nightly)

```bash
cd backend/training
python -m venv .venv-train && . .venv-train/Scripts/activate
pip install -r requirements-train.txt        # Unsloth + TRL, CUDA 12.1+

# one full generation: SFT -> DPO -> eval-gate -> (if it wins) export to Ollama
python train_cycle.py --gen 3 --incumbent qwen2.5:7b-instruct
```

If the gate PROMOTES, set `SYNAPSE_CHAT_MODEL=synapse-gen3` and restart the orchestrator. The town now serves the improved model and the loop continues. If it REJECTS, the town keeps the incumbent and gathers more debates. See [backend/training/](backend/training) and [backend/ops/](backend/ops) for scheduling it unattended.

## Anti-collapse safeguards (built in)

Free-form self-chat collapses. This design borrows the fixes that current research shows work:

- **DPO with a KL leash** (`beta`) to a frozen reference model.
- **Replay buffer / SPIN-style anchor**: each training set mixes in prior generations so the policy cannot drift off-distribution.
- **Eval-gate**: position-swapped LLM-judge head-to-head; a challenger must beat the incumbent before promotion. Nothing unevaluated is ever served.
- **Judge hygiene**: rubric-anchored scoring, penalties for clever-but-empty answers, position-bias swaps.

## Layout

```
synapse-city/
├── PLAN.md                       phased framework + rationale
├── backend/
│   ├── synapse/                  orchestrator (sim, memory, judge, harvest, server)
│   ├── training/                 GPU: Unsloth SFT, TRL DPO, eval-gate, GGUF export
│   ├── ops/                      unattended scheduling + snapshot/rollback
│   ├── run_headless.py           run the whole engine with no web/GPU
│   └── data/                     personas.json, world.json
└── frontend/                     react-three-fiber 3D city + live dashboards
```

## Phase status

- [x] Phase 0 Foundation (world, brains, config)
- [x] Phase 1 Interaction engine (memory, retrieval, reflection, conversations)
- [x] Phase 2 Self-learning loop (harvest, SFT/DPO, eval-gate, GGUF/Ollama, ELO)
- [x] Phase 3 3D visualization (r3f city, avatars, day/night, bloom)
- [x] Phase 4 Client showcase (loop dashboard, ELO board, live feed, presenter camera)
- [x] Phase 5 Autonomy & ops (nightly cycle, scheduling, rollback)

## Add your own models (give a model a body)

Each resident can run its **own** self-hosted model, so the town is a real, mixed
population of models that learn by talking to each other. Three ways to add one:

1. **In the app**: click **＋ Add model resident** (bottom-left). Pick a model that
   Ollama is serving, a name, a body (capsule / sphere / box / cone) and a hat, and
   it walks into town live.
2. **API**: `POST /api/agents` with `{ "name": "Atlas", "model": "qwen2.5:7b-instruct", "body": "box", "hat": "antenna", "home": "lab" }`. `GET /api/models` lists what Ollama is serving plus the available bodies/hats/districts.
3. **CLI**: `python backend/scripts/add_model.py "Atlas" qwen2.5:7b-instruct --body box`.

New residents are persisted to `backend/data/personas.json`, so they return after a
restart. Their conversations, debates, and judged preference pairs feed the same
self-learning loop, so **every model you add is also being trained** by living here.
The `model` field per persona routes each agent's turns to that model via Ollama.

## Deploy

- **Frontend** goes to Vercel (`frontend/`, Vite). It renders a living town on its
  own via the offline mock, so it demos with no backend. To point a deployed
  frontend at your real backend, set `VITE_SYNAPSE_API` and `VITE_SYNAPSE_WS`
  (see `frontend/.env.example`).
- **Backend** is a stateful, always-on process (sim loop + WebSocket + SQLite), so
  it runs on your **Nucbox / 3090 box**, not on serverless. Expose port 8000 to the
  deployed frontend, or just run the frontend locally next to it.
