# Catch-up training: train a batch of residents back-to-back NOW (they missed
# overnight training when the supervisor hung). Each goes through the real
# autonomous path (gpu_handover -> SFT/DPO -> gate on suite_v2 with the URL fix
# -> real verdict -> promote+brainswap if it wins). We stamp last_train before
# each so the supervisor doesn't fire its own cycle and collide.
param([string[]]$Residents = @('sol','tam','moss','nyx','pip','orin','bram','cade'))
$ErrorActionPreference = "Continue"
$Root = "C:\synapse-city\backend"
$Py   = "$Root\.venv\Scripts\python.exe"
$lock = "C:\Users\nirvana\.synapse\TRAINING.lock"
$genf = "C:\Users\nirvana\.synapse\next_gen.txt"
$ltf  = "C:\Users\nirvana\.synapse\last_train.txt"

# wait for any in-flight (supervisor) training to finish first
$w = 0
while ((Test-Path $lock) -and $w -lt 160) { Start-Sleep 15; $w++ }

foreach ($r in $Residents) {
  Set-Content $ltf (Get-Date -Format s)               # hold off the supervisor
  $gen = if (Test-Path $genf) { [int](Get-Content $genf) } else { 20 }
  if ($gen -lt 20) { $gen = 20 }                       # avoid old eval/genN.json
  Set-Content $genf ($gen + 1)
  $model = & $Py -c "import json;d=json.load(open(r'$Root\data\personas.json',encoding='utf-8'));print(next(a['model'] for a in d['agents'] if a['id']=='$r'))"
  Write-Output ("=== [{0}] training {1} (gen {2}, base {3}) ===" -f (Get-Date -Format HH:mm), $r, $gen, $model)
  powershell -NoProfile -ExecutionPolicy Bypass -File "$Root\ops\gpu_handover.ps1" `
      -Gen $gen -Resident $r -Incumbent $model 2>&1 |
      Out-File "$Root\run\catchup_${r}_g${gen}.log"
  # surface the verdict
  $ev = "$Root\run\eval\gen$gen.json"
  if (Test-Path $ev) {
    $j = Get-Content $ev -Raw | ConvertFrom-Json
    Write-Output ("    {0}: challenger {1:P0} vs base {2:P0} -> {3}" -f $r, $j.challenger_rate, $j.incumbent_rate, $(if ($j.promote) { "*** PROMOTED ***" } else { "reject" }))
  }
  Start-Sleep 3
}
Write-Output "CATCHUP BATCH DONE"
