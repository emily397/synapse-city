"""Phase 2 (GPU): DPO on the Arena's judged preference pairs. This is where the
town's disagreements actually improve the model. The DPO beta term is a KL leash
to the reference model: the core anti-collapse safeguard.

    python train_dpo.py --gen 3            # start from base
    python train_dpo.py --gen 3 --from-sft # continue from the gen3 SFT adapter
"""
from __future__ import annotations

import argparse

from datasets import Dataset

from common import BASE_MODEL, MAX_SEQ, ADAPTERS, with_replay


def main(gen: int, from_sft: bool, beta: float, epochs: float):
    from unsloth import FastLanguageModel, PatchDPOTrainer
    PatchDPOTrainer()                       # unsloth speed patch for DPO
    from trl import DPOTrainer, DPOConfig

    start = str(ADAPTERS / f"gen{gen}-sft") if from_sft else BASE_MODEL
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=start, max_seq_length=MAX_SEQ, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=1337)

    rows = with_replay(gen, "dpo")          # {prompt, chosen, rejected}
    if not rows:
        raise SystemExit(f"No DPO pairs for gen{gen}. Run more Arena debates.")
    ds = Dataset.from_list(rows)

    out = ADAPTERS / f"gen{gen}-dpo"
    trainer = DPOTrainer(
        model=model, ref_model=None, tokenizer=tokenizer, train_dataset=ds,
        args=DPOConfig(
            output_dir=str(out), per_device_train_batch_size=1,
            gradient_accumulation_steps=8, warmup_steps=5,
            num_train_epochs=epochs, learning_rate=5e-6, logging_steps=5,
            optim="adamw_8bit", lr_scheduler_type="cosine", seed=1337,
            beta=beta, max_length=MAX_SEQ, max_prompt_length=512,
            report_to="none"))
    trainer.train()
    model.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))
    print(f"[ok] DPO adapter -> {out}  (pairs={len(rows)}, beta={beta})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--from-sft", action="store_true")
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--epochs", type=float, default=1.0)
    a = ap.parse_args()
    main(a.gen, a.from_sft, a.beta, a.epochs)
