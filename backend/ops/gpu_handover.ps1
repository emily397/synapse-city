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
    [string]$Resident = "",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$Lock   = "C:\Users\nirvana\.synapse\TRAINING.lock"
$Repo   = "C:\synapse-city"
$RunDir = "$Repo\backend\run"
$Report = "$RunDir\REPORT.md"
$JudgeTag = "qwen2.5:14b"

function Step($m) { Write-Host ("==> " + $m) }

# -- 1. pause: the lock makes the SIM rest (no model calls) while the backend
#    stays UP and connected, so the public 3D town never goes offline. -------
Step "pausing town (TRAINING.lock; sim rests, backend stays live)"
Set-Content $Lock ("training gen{0} started {1}" -f $Gen, (Get-Date -Format s))
Start-Sleep -Seconds 4    # let the sim notice the lock and stop LLM calls

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
          "--gen $Gen --incumbent '$Incumbent' " +
          $(if ($Resident) { "--resident '$Resident' " } else { "" }) +
          "2>&1 | tee /root/train_gen$Gen$Resident.log"
  wsl -d Ubuntu -u root -- bash -c $bash
  $trainExit = $LASTEXITCODE
  Write-Host ("    train_cycle exit: " + $trainExit)

  # -- 4. if the gate promoted, register the GGUF with Windows Ollama --------
  # Resident cycles namespace BOTH the adapter tree (adapters\<res>\...) and the
  # Ollama tag (<res>-gen<N>). Unsloth also sometimes appends an extra "_gguf" to
  # the export dir, so we SEARCH for the real Modelfile rather than hard-coding a
  # path (the old hard-coded path is why promotions never registered).
  $promotedFile = "$RunDir\promoted.json"
  if ($Resident) {
    $searchRoot = "$RunDir\adapters\$Resident"
    $regTag = "$Resident-gen$Gen"
  } else {
    $searchRoot = "$RunDir\adapters"
    $regTag = "synapse-gen$Gen"
  }
  $modelfile = $null
  if (Test-Path $searchRoot) {
    $modelfile = Get-ChildItem $searchRoot -Recurse -Filter "Modelfile" -ErrorAction SilentlyContinue |
      Where-Object { $_.DirectoryName -match "gen$Gen-dpo" } |
      Sort-Object LastWriteTime | Select-Object -Last 1 | ForEach-Object { $_.FullName }
  }
  if ((Test-Path $promotedFile) -and $modelfile -and (Test-Path $modelfile)) {
    $pj = Get-Content $promotedFile -Raw | ConvertFrom-Json
    if ($pj.gen -eq $Gen) {
      Step "PROMOTED: registering $regTag in Ollama (from $modelfile)"
      # cd into the gguf dir so the Modelfile's relative FROM resolves
      Push-Location (Split-Path $modelfile)
      ollama create "$regTag" -f $modelfile
      $regExit = $LASTEXITCODE
      Pop-Location
      if ($regExit -eq 0) {
        $promoted = $true
        # verify it actually landed in Ollama (no more phantom promotions)
        Start-Sleep 2
        $tags = (Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 15).models.name
        if ($tags -contains "${regTag}:latest" -or $tags -contains $regTag) {
          Step "VERIFIED: $regTag is live in Ollama"
        } else {
          Write-Warning "register reported success but $regTag not in /api/tags"
        }
      } else {
        Write-Warning "ollama create failed for $regTag (exit $regExit)"
      }
    }
  } elseif (Test-Path $promotedFile) {
    $pj = Get-Content $promotedFile -Raw | ConvertFrom-Json
    if ($pj.gen -eq $Gen) { Write-Warning "PROMOTED gen$Gen but no Modelfile found under $searchRoot — export may have failed" }
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
# -- weekly external regression check: GSM8K slice via lm-eval (WSL) --------
$gsmMarker = "C:\Users\nirvana\.synapse\gsm8k_" + (Get-Date -UFormat %V)   # ISO week
if (-not $DryRun -and -not (Test-Path $gsmMarker)) {
  Set-Content $gsmMarker "started"
  Step "weekly GSM8K regression slice (external, catches narrow overfitting)"
  $gsmBash = "WINIP=`$(ip route show default | awk '{print `$3}'); " +
    "/root/proprietary-model/.venv/bin/python -m lm_eval " +
    "--model local-chat-completions " +
    "--model_args base_url=http://`${WINIP}:11434/v1/chat/completions,model=$Incumbent,num_concurrent=1 " +
    "--tasks gsm8k --limit 50 --apply_chat_template 2>&1 | tail -5"
  $gsm = wsl -d Ubuntu -u root -- bash -c $gsmBash
  $gsmLine = [string]($gsm | Select-String "gsm8k|acc" | Select-Object -First 1)
  Add-Content $Report ("- {0} :: gsm8k slice ({1}) :: {2}" -f
    (Get-Date -Format s), $Incumbent, ($gsmLine -replace '\s+', ' '))
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
