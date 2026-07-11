# Put the backend online from your own machine (e.g. the Nucbox) with a public
# HTTPS/WSS URL, no host account needed. Great for the REAL town: run this where
# Ollama + the 3090 live.
#
# Prereqs: pip install -r ../requirements.txt ; cloudflared installed.
# Set DATABASE_URL (from the Neon console) for durable shared state, and
# SYNAPSE_LLM_BACKEND=ollama to use your local models.
#
#   $env:DATABASE_URL   = "postgresql://...neon.tech/neondb?sslmode=require"
#   $env:SYNAPSE_LLM_BACKEND = "ollama"      # or "mock"
#   .\serve_public.ps1
#
# It prints a https://<name>.trycloudflare.com URL. Point the Vercel frontend at
# it:  VITE_SYNAPSE_API=https://<name>.trycloudflare.com
#      VITE_SYNAPSE_WS=wss://<name>.trycloudflare.com   then redeploy the frontend.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Start-Process -NoNewWindow python -ArgumentList "-m","uvicorn","synapse.server:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $root
Start-Sleep -Seconds 4
Write-Host "Backend on http://127.0.0.1:8000  (opening public tunnel...)"
cloudflared tunnel --url http://localhost:8000 --no-autoupdate
