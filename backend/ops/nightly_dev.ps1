# GUARANTEED overnight development. Task Scheduler runs this at ~2 AM (with
# StartWhenAvailable, so it fires even if the PC was asleep at 2). It is
# INDEPENDENT of the supervisor — that independence is the 100%-overnight
# guarantee. It teaches the town, then trains every ready resident in sequence
# through the real gate (real verdicts now that the URL bug is fixed). Promotions
# swap the resident's brain; trained "genes" let bonded couples reproduce.
$ErrorActionPreference = "Continue"
$Root = "C:\synapse-city\backend"
$Py   = "$Root\.venv\Scripts\python.exe"
$lock = "C:\Users\nirvana\.synapse\TRAINING.lock"
$stamp = "C:\Users\nirvana\.synapse\nightly_dev_$((Get-Date -Format yyyyMMdd)).done"
if (Test-Path $stamp) { exit }                 # already ran tonight
if (Test-Path $lock)  { exit }                 # something is already training

# 1) the town teaches itself (cross-model peer transfer)
Set-Content "C:\Users\nirvana\.synapse\last_teach.txt" (Get-Date -Format s)
Set-Content $lock ("nightly-teach " + (Get-Date -Format s))
Start-Sleep 5
& $Py "$Root\training\peer_teach.py" --per-family 6 2>&1 |
    Out-File "$Root\run\nightly_teach_$((Get-Date -Format yyyyMMdd)).log"
Remove-Item $lock -Force -ErrorAction SilentlyContinue

# 2) train every ready resident in sequence (catchup_train stamps last_train so
#    the supervisor's own night training doesn't collide)
$order = @('sol','tam','moss','nyx','pip','orin','bram','quinn','wren','cade',
           'forge','phaedra','lumi','juniper','vera','rune')
powershell -NoProfile -ExecutionPolicy Bypass -File "$Root\ops\catchup_train.ps1" `
    -Residents $order 2>&1 |
    Out-File "$Root\run\nightly_batch_$((Get-Date -Format yyyyMMdd)).log"

Set-Content $stamp "done"
