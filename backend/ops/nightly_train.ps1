# Nightly self-improvement cycle for the RTX 3090. Schedule daily (Task Scheduler).
# Snapshots the DB, trains the next generation, gates it, and (only on a win)
# promotes it for the town to pick up on next restart.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent          # backend/
$run  = Join-Path $root "run"
$ts   = Get-Date -Format "yyyyMMdd_HHmmss"

# 1) snapshot (reversible)
New-Item -ItemType Directory -Force (Join-Path $run "snapshots") | Out-Null
Copy-Item (Join-Path $run "synapse.db") (Join-Path $run "snapshots\synapse_$ts.db") -Force
if (Test-Path (Join-Path $run "promoted.json")) {
  Copy-Item (Join-Path $run "promoted.json") (Join-Path $run "snapshots\promoted_$ts.json") -Force
}

# 2) next generation number from the datasets already harvested by the town
$gens = Get-ChildItem (Join-Path $run "datasets") -Filter "gen*_dpo.jsonl" -ErrorAction SilentlyContinue |
  ForEach-Object { [int]($_.BaseName -replace 'gen(\d+)_dpo','$1') }
if (-not $gens) { Write-Host "No harvested generations yet. Let the town run."; exit 0 }
$gen = ($gens | Measure-Object -Maximum).Maximum

# 3) train + gate + export (train_cycle only promotes on an eval win)
$incumbent = if (Test-Path (Join-Path $run "promoted.json")) {
  (Get-Content (Join-Path $run "promoted.json") | ConvertFrom-Json).model
} else { "qwen2.5:7b-instruct" }

New-Item -ItemType Directory -Force (Join-Path $run "logs") | Out-Null
$log = Join-Path $run "logs\train_$ts.log"
Push-Location (Join-Path $root "training")
python train_cycle.py --gen $gen --incumbent $incumbent *>&1 | Tee-Object $log
Pop-Location
Write-Host "Nightly cycle for gen$gen done. Log: $log"
