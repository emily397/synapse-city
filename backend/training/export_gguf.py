"""Phase 2 (GPU): merge an adapter, convert to GGUF, and register it in Ollama so
the live town can serve it.

    python export_gguf.py --gen 3 --adapter dpo --quant q4_k_m

Produces run/adapters/gen3-dpo-gguf/ and runs `ollama create synapse-gen3`.
Uses Unsloth's built-in GGUF export (wraps llama.cpp).
"""
from __future__ import annotations

import argparse
import subprocess

from common import BASE_MODEL, MAX_SEQ, ADAPTERS


def main(gen: int, which: str, quant: str, ollama_tag: str | None):
    from unsloth import FastLanguageModel

    adapter = ADAPTERS / f"gen{gen}-{which}"
    if not adapter.exists():
        raise SystemExit(f"Adapter not found: {adapter}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(adapter), max_seq_length=MAX_SEQ, load_in_4bit=True)

    gguf_dir = ADAPTERS / f"gen{gen}-{which}-gguf"
    # Merges LoRA into the base and writes a quantized GGUF + a Modelfile.
    model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method=quant)
    print(f"[ok] GGUF -> {gguf_dir}")

    tag = ollama_tag or f"synapse-gen{gen}"
    modelfile = gguf_dir / "Modelfile"
    if modelfile.exists():
        subprocess.run(["ollama", "create", tag, "-f", str(modelfile)], check=True)
        print(f"[ok] ollama model created: {tag}")
    else:
        print(f"[warn] no Modelfile in {gguf_dir}; import the .gguf manually.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--adapter", choices=["sft", "dpo"], default="dpo")
    ap.add_argument("--quant", default="q4_k_m")
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()
    main(a.gen, a.adapter, a.quant, a.tag)
