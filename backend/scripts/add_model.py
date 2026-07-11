"""Add a self-hosted model to the running town as a resident (with a body).

    python scripts/add_model.py "Atlas" qwen2.5:7b-instruct --body box --hat antenna

Requires the orchestrator to be running (uvicorn synapse.server:app). The new
resident appears live in every connected 3D client and is persisted to
data/personas.json so it returns after a restart.
"""
import argparse
import json
import urllib.request

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("model", nargs="?", default="")
    ap.add_argument("--role", default="Resident")
    ap.add_argument("--home", default="plaza")
    ap.add_argument("--body", default="capsule", choices=["capsule", "sphere", "box", "cone"])
    ap.add_argument("--hat", default="antenna",
                    choices=["none", "antenna", "cap", "beanie", "crown", "halo"])
    ap.add_argument("--color", default=None)
    ap.add_argument("--api", default="http://localhost:8000")
    a = ap.parse_args()

    payload = {"name": a.name, "model": a.model, "role": a.role, "home": a.home,
               "body": a.body, "hat": a.hat}
    if a.color:
        payload["color"] = a.color
    req = urllib.request.Request(
        f"{a.api}/api/agents", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        print(f"[ok] {a.name} joined town:", r.read().decode())

if __name__ == "__main__":
    main()
