# Heal/finish a resident promotion the running (old) handover couldn't register.
# Finds the real GGUF Modelfile under the resident's namespaced adapter tree
# (Unsloth may append "_gguf"), registers <resident>-gen<N> in Windows Ollama,
# verifies it in /api/tags, and (if promoted) ensures personas.json points to it.
#
#   .\register_resident_model.ps1 -Resident quinn -Gen 8
param(
  [Parameter(Mandatory=$true)][string]$Resident,
  [Parameter(Mandatory=$true)][int]$Gen
)
$ErrorActionPreference = "Stop"
$RunDir = "C:\synapse-city\backend\run"
$Personas = "C:\synapse-city\backend\data\personas.json"
$tag = "$Resident-gen$Gen"
$root = "$RunDir\adapters\$Resident"

if (-not (Test-Path $root)) { Write-Host "no adapter tree for $Resident at $root"; exit 1 }
$mf = Get-ChildItem $root -Recurse -Filter "Modelfile" -ErrorAction SilentlyContinue |
  Where-Object { $_.DirectoryName -match "gen$Gen-dpo" } |
  Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $mf) { Write-Host "no Modelfile for gen$Gen under $root — export did not finish"; exit 2 }

Write-Host "registering $tag from $($mf.FullName)"
Push-Location $mf.DirectoryName
ollama create $tag -f $mf.FullName
$ok = $LASTEXITCODE
Pop-Location
if ($ok -ne 0) { Write-Host "ollama create failed (exit $ok)"; exit 3 }

Start-Sleep 2
$tags = (Invoke-RestMethod http://localhost:11434/api/tags -TimeoutSec 20).models.name
if (($tags -contains "${tag}:latest") -or ($tags -contains $tag)) {
  Write-Host "VERIFIED live in Ollama: $tag"
} else {
  Write-Host "WARNING: create returned 0 but $tag not in /api/tags"; exit 4
}

# make sure personas.json points the resident at its new self
$d = Get-Content $Personas -Raw | ConvertFrom-Json
$cur = ($d.agents | Where-Object { $_.id -eq $Resident }).model
if ($cur -ne $tag) {
  ($d.agents | Where-Object { $_.id -eq $Resident }).model = $tag
  ($d | ConvertTo-Json -Depth 12) | Set-Content $Personas -Encoding utf8
  Write-Host "personas.json: $Resident $cur -> $tag"
} else {
  Write-Host "personas.json already set: $Resident = $tag"
}
Write-Host "DONE: $Resident now serves its trained self ($tag)"
