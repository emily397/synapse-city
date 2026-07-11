# Synapse City

A living 3D suburb where your open-source models live, talk, teach each other, and get measurably smarter. Runs fully local on the Nucbox plus RTX 3090, with zero human in the loop.

Not a chatbot demo. A closed self-improvement loop dressed as a city you can fly a camera through and show a client.

---

## The core idea (why this actually trains models, not just "chats")

Free-form models chatting and back-propagating on every word **collapses** (degeneration, mode collapse). So Synapse City does not do that. It runs the loop that current research shows works:

```
   INTERACT            HARVEST             DISTILL             PROMOTE
  agents live   ->   log + judge every ->  build SFT + DPO ->  LoRA fine-tune,
  in the town        exchange (LLM-as-     datasets from the   eval-gate, hot-swap
  & converse         judge reward)         best/worst exchanges the winner,
                                                                then loop repeats
```

Every district in the city produces a *different kind* of training signal:

| District | Activity | Training signal produced |
|---|---|---|
| **The Lab** | hypotheses, Q&A | SFT (high-quality reasoning traces) |
| **The Workshop** | build/solve tasks | SFT (tool-use, step-by-step) |
| **The School** | teaching / explaining | Distillation pairs (teacher to student) |
| **The Arena** | debates, judged by a mentor agent | **DPO preference pairs** (winner vs loser) |
| **The Studio** | creative / divergent | Diversity samples (anti-collapse) |
| **Homes (night)** | "sleep" | Reflection + memory consolidation |

The Arena is the engine: two agents argue, a **Judge agent** scores them, and you get `(prompt, chosen, rejected)` triples for Direct Preference Optimization. Self-rewarding, no human labels.

---

## Phased roll-out

### Phase 0: Foundation `[world + brains]`
World-state model, tick scheduler, persona definitions, LLM gateway (Ollama, or a built-in mock so it runs before the GPU is wired). Deterministic, testable headless.

### Phase 1: Interaction engine `[they come alive]`
Generative-Agents-style cognition: memory stream, embedding retrieval, reflection, planning. Agents choose actions, walk to districts, hold real multi-turn conversations, remember each other.

### Phase 2: Self-learning loop `[they get smarter]`
Interaction logger, LLM-as-judge scorer, SFT + DPO dataset builders, Unsloth QLoRA trainer, GGUF export, Ollama hot-swap. **Safety gates**: an eval harness plus ELO must beat the incumbent before an adapter is promoted; KL / reference regularization plus a replay buffer prevent collapse.

### Phase 3: 3D visualization `[the wow]`
react-three-fiber low-poly suburb, avatars with pathfinding, live speech bubbles, day/night cycle, a camera that follows conversations. Streams live world state over WebSocket.

### Phase 4: Client showcase `[the pitch]`
HUD dashboards: live training curves, dataset growth, model **ELO leaderboard**, "generations" counter, current-conversation feed, per-agent "brain" activity. Cinematic *presenter mode*.

### Phase 5: Autonomy & ops `[24/7 unattended]`
Scheduler runs it forever. Watchdog, checkpoint / rollback, collapse detectors, resource caps for the 3090. Walk away; come back to a smarter town.

---

## Hardware placement

- **RTX 3090 (24GB)**: Ollama serving (7B agents; QLoRA fits ~7B comfortably) plus nightly Unsloth QLoRA training runs.
- **Nucbox**: orchestrator (FastAPI + sim loop + SQLite), WebSocket bridge, serves the 3D frontend. CPU-only, light.

Runs **now** with the mock brain (no GPU) so the city is alive and demoable immediately. Point it at Ollama to make it real.
