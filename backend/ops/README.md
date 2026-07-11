# Ops: running Synapse City unattended

Two processes, two boxes. The town runs continuously; training runs nightly while
the town is snapshotted, so the single 3090 never serves and trains at full tilt
at the same moment.

## 1. Run the town (Nucbox, always on)

```powershell
# ops/run_town.ps1
$env:SYNAPSE_LLM_BACKEND = "ollama"
$env:SYNAPSE_CHAT_MODEL  = (Get-Content ..\run\promoted.json -ErrorAction SilentlyContinue |
                            ConvertFrom-Json).model  # falls back below if none
if (-not $env:SYNAPSE_CHAT_MODEL) { $env:SYNAPSE_CHAT_MODEL = "qwen2.5:7b-instruct" }
uvicorn synapse.server:app --host 0.0.0.0 --port 8000
```

Keep it alive across reboots with NSSM (`nssm install SynapseCity ...`) or Task
Scheduler "At startup". The frontend (`npm run build` then any static host, or
`npm run dev`) points at this box.

## 2. Nightly self-improvement (3090)

Schedule `ops/nightly_train.ps1` once a day (Task Scheduler, e.g. 03:00). It:

1. snapshots the SQLite db (so a bad night is always reversible),
2. runs one generation: SFT -> DPO -> eval-gate -> export,
3. only writes `run/promoted.json` if the challenger BEAT the incumbent.

The town reads `promoted.json` on next restart, so promotion is atomic and gated.

## 3. Snapshot / rollback

```powershell
ops\snapshot.ps1              # copy run\synapse.db + promoted.json -> run\snapshots\<ts>
ops\rollback.ps1 <ts>         # restore a snapshot, then restart the town
```

## 4. Resource caps (24GB card)

- Serve a 7B at q4_k_m (~6GB) so training (~10GB QLoRA) and serving can coexist if
  you ever overlap. Prefer not to overlap: the nightly job pauses nothing but
  simply runs while traffic is low.
- `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1` keep VRAM predictable.
- Drop the training base to Qwen2.5-3B / Llama-3.2-3B (`SYNAPSE_BASE_MODEL`) for
  more self-play rounds per night.

## 5. Collapse watchdog

`eval_gate` is the guard: a generation that fails to beat the incumbent is never
promoted, so the town can never regress below its current best. Track ELO and the
per-generation winrate in `run/eval/*.json`; a run of rejections means the current
signal is exhausted (raise conversation diversity, add districts, or swap the base).
