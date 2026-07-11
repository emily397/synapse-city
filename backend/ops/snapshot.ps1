# Snapshot the town's state (DB + promoted model pointer).
$root = Split-Path $PSScriptRoot -Parent
$run  = Join-Path $root "run"
$ts   = Get-Date -Format "yyyyMMdd_HHmmss"
$dst  = Join-Path $run "snapshots"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item (Join-Path $run "synapse.db") (Join-Path $dst "synapse_$ts.db") -Force
if (Test-Path (Join-Path $run "promoted.json")) {
  Copy-Item (Join-Path $run "promoted.json") (Join-Path $dst "promoted_$ts.json") -Force
}
Write-Host "Snapshot: $ts"
