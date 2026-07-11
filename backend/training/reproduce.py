"""Reproduction: two same-base residents produce a child model.

    python reproduce.py --base unsloth/Qwen2.5-7B-Instruct-bnb-4bit \
        --adapter-a run/adapters/quinn-gen2-dpo --adapter-b run/adapters/wren-gen1-dpo \
        --child-tag child-quinn-wren-gen1 --name "Sable"

Mechanism (standard practice, technically sound):
  1. Both parents' LoRA adapters were trained on the SAME base architecture.
  2. Their adapter tensors are weight-averaged (a linear "model soup" merge):
     the child inherits both parents' learned behaviour in weight space.
  3. The merged adapter is fused into the base, exported to GGUF, and
     registered in Ollama under the child tag.
  4. A child persona is printed (and optionally POSTed to the live town via
     --spawn http://127.0.0.1:8000) so the newborn walks into Synapse with its
     own body; its own life then diverges its own dataset -> its own gens.

Run inside WSL with the training venv (needs GPU + unsloth). Requires that
personal adapters exist (first per-resident training cycles must have run) and
that both adapters share base + LoRA rank. NOTE: give per-resident training
runs distinct output dirs (adapter paths are the parent 'genes').
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch


def average_adapters(a_dir: str, b_dir: str, out_dir: str):
    from safetensors.torch import load_file, save_file
    a_p = Path(a_dir) / "adapter_model.safetensors"
    b_p = Path(b_dir) / "adapter_model.safetensors"
    a, b = load_file(str(a_p)), load_file(str(b_p))
    assert set(a) == set(b), "adapter key mismatch: parents not compatible"
    child = {k: (a[k].float() + b[k].float()) / 2.0 for k in a}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # copy adapter config from parent A (same base/rank by assertion above)
    cfg = (Path(a_dir) / "adapter_config.json").read_text(encoding="utf-8")
    (out / "adapter_config.json").write_text(cfg, encoding="utf-8")
    save_file({k: v.to(torch.bfloat16) for k, v in child.items()},
              str(out / "adapter_model.safetensors"))
    print(f"[ok] child adapter (weight-averaged) -> {out}")
    return str(out)


def export_child(base: str, child_adapter: str, tag: str, quant: str = "q4_k_m"):
    from unsloth import FastLanguageModel
    model, tok = FastLanguageModel.from_pretrained(
        model_name=child_adapter, max_seq_length=2048, load_in_4bit=True)
    gguf_dir = Path(child_adapter).with_name(Path(child_adapter).name + "-gguf")
    model.save_pretrained_gguf(str(gguf_dir), tok, quantization_method=quant)
    print(f"[ok] child GGUF -> {gguf_dir}")
    print(f"[next] register: ollama create {tag} -f \"{gguf_dir / 'Modelfile'}\"")
    return gguf_dir


def child_persona(name: str, tag: str, pa: str, pb: str) -> dict:
    return {
        "name": name, "model": tag, "role": "a newcomer finding their place",
        "home": "plaza", "body": "sphere", "hat": "none",
        "voice": f"Young and searching; echoes of both {pa} and {pb} in how they think",
        "goal": "figure out who they are, apart from where they came from",
        "is_judge": False,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter-a", required=True)
    ap.add_argument("--adapter-b", required=True)
    ap.add_argument("--child-tag", required=True)
    ap.add_argument("--name", default="Sable")
    ap.add_argument("--spawn", default=None,
                    help="backend URL to POST the child persona to (walks into town)")
    a = ap.parse_args()
    child = average_adapters(a.adapter_a, a.adapter_b,
                             str(Path(a.adapter_a).parent / f"{a.child_tag}-adapter"))
    export_child(a.base, child, a.child_tag)
    persona = child_persona(a.name, a.child_tag,
                            Path(a.adapter_a).name.split("-")[0],
                            Path(a.adapter_b).name.split("-")[0])
    print(json.dumps(persona, indent=2))
    if a.spawn:
        import httpx
        r = httpx.post(f"{a.spawn}/api/agents", json=persona, timeout=30)
        print(f"[spawn] {r.status_code}: {a.name} walks into town")
