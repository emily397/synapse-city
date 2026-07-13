"""Phase 2 (GPU): SFT a QLoRA adapter on a generation's high-quality exchanges.

    python train_lora.py --gen 3

Trains an adapter into run/adapters/gen3-sft/. ~7B QLoRA fits comfortably on a
24GB RTX 3090 (~10GB). Runs on the training box, not the Nucbox.
"""
from __future__ import annotations

import argparse

from datasets import Dataset

from common import BASE_MODEL, MAX_SEQ, ADAPTERS, with_replay


def main(gen: int, epochs: float):
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL, max_seq_length=MAX_SEQ, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=1337)

    rows = with_replay(gen, "sft")
    if not rows:
        raise SystemExit(f"No SFT data for gen{gen}. Let the town run longer.")

    def fmt(ex):
        return {"text": tokenizer.apply_chat_template(
            ex["messages"], tokenize=False, add_generation_prompt=False)}

    ds = Dataset.from_list(rows).map(fmt, remove_columns=["messages"])

    out = ADAPTERS / f"gen{gen}-sft"
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        args=SFTConfig(
            output_dir=str(out), per_device_train_batch_size=2,
            gradient_accumulation_steps=4, warmup_steps=5,
            num_train_epochs=epochs, learning_rate=2e-4, logging_steps=5,
            optim="adamw_8bit", weight_decay=0.01, lr_scheduler_type="cosine",
            seed=1337, dataset_text_field="text", max_seq_length=MAX_SEQ,
            report_to="none"))
    trainer.train()
    model.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))
    print(f"[ok] SFT adapter -> {out}  (rows={len(rows)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    # Small per-resident corpora overfit fast; one clean pass over
    # verifier-shaped targets beats two passes that memorise noise.
    ap.add_argument("--epochs", type=float, default=1.0)
    a = ap.parse_args()
    main(a.gen, a.epochs)
