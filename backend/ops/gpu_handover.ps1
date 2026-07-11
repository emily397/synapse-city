# GPU handover: pause the town, free the GPU, run one training generation in
# WSL, register the result in Ollama (Windows side), resume the town.
#
#   .\gpu_handover.ps1 -Gen 1 -Incumbent qwen2.5:7b-instruct
#   .\gpu_handover.ps1 -DryRun          # exercises pause/unload/resume only
#
# Requires: WSL Ubuntu with the training venv at /root/proprietary-model/.venv
# and working GPU passthrough (nvidia-smi inside WSL).
param(
    [int]$Gen = 1,
    [string]$Incumbent = "qwen2.5:7b-instruct",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$Lock   = "C:\Users\nirvana\.synapse\TRAINING.lock"
$Repo   = "C:\synapse-city"
$RunDir = "$Repo\backend\run"
$Report = "$RunDir\REPORT.md"
$JudgeTag = "qwen2.5:14b"

function Step($m) { Write-Host ("==> " + $m) }

# -- 1. pause: lock stops the supervisor from resurrecting the backend -------
Step "pausing town (TRAINING.lock + stop uvicorn)"
Set-Content $Lock ("training gen{0} started {1}" -f $Gen, (Get-Date -Format s))
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'synapse\.server' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# -- 2. free VRAM: unload every model Ollama holds ----------------------------
Step "unloading Ollama models"
try {
  $ps = Invoke-RestMethod http://localhost:11434/api/ps -TimeoutSec 10
  foreach ($m in $ps.models) {
    $b = @{ model = $m.name; prompt = ""; stream = $false; keep_alive = 0 } | ConvertTo-Json
    try { $null = Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -Body $b -ContentType "application/json" -TimeoutSec 60 } catch {}
    Write-Host ("    unloaded " + $m.name)
  }
} catch { Write-Host "    (ollama not reachable or nothing loaded)" }

$promoted = $false
$note = "dry-run"
if (-not $DryRun) {
  # -- 3. train in WSL (GPU): SFT -> DPO -> suite eval-gate -------------------
  Step "training gen$Gen in WSL (this is the long part)"
  $bash = "WINIP=`$(ip route show default | awk '{print `$3}'); " +
          "cd /mnt/c/synapse-city/backend/training && " +
          "SYNAPSE_OLLAMA_URL=http://`${WINIP}:11434 " +
          "/root/proprietary-model/.venv/bin/python train_cycle.py " +
          "--gen $Gen --incumbent '$Incumbent' 2>&1 | tee /root/train_gen$Gen.log"
  wsl -d Ubuntu -u root -- bash -c $bash
  $trainExit = $LASTEXITCODE
  Write-Host ("    train_cycle exit: " + $trainExit)

  # -- 4. if the gate promoted, register the GGUF with Windows Ollama --------
  $promotedFile = "$RunDir\promoted.json"
  $modelfile = "$RunDir\adapters\gen$Gen-dpo-gguf\Modelfile"
  if ((Test-Path $promotedFile) -and (Test-Path $modelfile)) {
    $pj = Get-Content $promotedFile -Raw | ConvertFrom-Json
    if ($pj.gen -eq $Gen) {
      Step "PROMOTED: registering synapse-gen$Gen in Ollama"
      ollama create "synapse-gen$Gen" -f $modelfile
      $promoted = $true
    }
  }
  # -- 5. report line ---------------------------------------------------------
  $evalFile = "$RunDir\eval\gen$Gen.json"
  $note = "no eval file"
  if (Test-Path $evalFile) {
    $e = Get-Content $evalFile -Raw | ConvertFrom-Json
    $note = ("gen{0} | mode={1} | challenger={2:P1} incumbent={3:P1} | p={4:N4} | promoted={5}" -f
      $Gen, $e.mode, $e.challenger_rate, $e.incumbent_rate, $e.sign_test_p, $promoted)
  }
}
if (-not (Test-Path $Report)) {
  Set-Content $Report "# Synapse City training report`n"
}
Add-Content $Report ("- {0} :: {1}" -f (Get-Date -Format s), $note)
Step ("report: " + $note)

# -- 6. resume: drop the lock, supervisor revives the backend; re-pin judge --
Step "resuming town"
Remove-Item $Lock -Force -ErrorAction SilentlyContinue
$up = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep 2
  if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { $up = $true; break }
}
if (-not $up) { Write-Warning "backend did not come back within 60s; check the supervisor" }
try {
  $b = @{ model = $JudgeTag; prompt = ""; stream = $false; keep_alive = "24h" } | ConvertTo-Json
  $null = Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -Body $b -ContentType "application/json" -TimeoutSec 300
  Step "judge re-pinned"
} catch { Write-Warning "judge re-pin failed (will load on demand)" }
Step ("done. backend up: " + $up)
