# Restore a snapshot:  ops\rollback.ps1 20260711_030000
param([Parameter(Mandatory=$true)][string]$ts)
$root = Split-Path $PSScriptRoot -Parent
$run  = Join-Path $root "run"
$snap = Join-Path $run "snapshots\synapse_$ts.db"
if (-not (Test-Path $snap)) { throw "No snapshot for $ts" }
Copy-Item $snap (Join-Path $run "synapse.db") -Force
$prom = Join-Path $run "snapshots\promoted_$ts.json"
if (Test-Path $prom) { Copy-Item $prom (Join-Path $run "promoted.json") -Force }
Write-Host "Rolled back to $ts. Restart the orchestrator to apply."
