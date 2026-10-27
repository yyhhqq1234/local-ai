#!/usr/bin/env python
"""train_qlora9b.py — 9B 双能力（RE + NSFW）QLoRA，12 GB 专用。

与 train_qlora.py 的区别：
  · 支持 9B 档（Qwen3.5 / OxCoder-9B，多模态基座，走 ImageTextToText）
  · 支持 stage 预设（re / nsfw / joint），LR/r/ctx 按段差异化
  · LoRA target 自动探测：列出实际命中的 Linear 名，避免 qwen3_5 混合线性层命名差异踩空
  · 显存烟囱检查：启动即报预算，OOM 前一档降配

用法:
  python train_qlora9b.py --base train/models/OxCoder-9B-abliterated \
      --data train/data/mix-re.jsonl --stage re   --dry-run
  python train_qlora9b.py --base ... --data train/data/mix-re.jsonl   --stage re
  python train_qlora9b.py --base ... --data train/data/mix-nsfw.jsonl --stage nsfw
"""
import argparse
import json
import os
import sys

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(TRAIN_ROOT, "hf"))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# stage 预设：三段的差异是刻意的，不要统一
PRESETS = {
    # RE：要长上下文看伪代码/反汇编，r 高一些吃下工具语法
    "re":    dict(ctx=2048, r=32, alpha=64, lr=1e-4, epochs=4.0, ga=16),
    # NSFW：低 LR + 低 r，目标是注入分布而不重排权重
    "nsfw":  dict(ctx=2048, r=16, alpha=32, lr=5e-5, epochs=2.0, ga=16),
    # joint：一次性混训，lr 更低求稳
    "joint": dict(ctx=2048, r=24, alpha=48, lr=6e-5, epochs=3.0, ga=16),
}

# 优先挂 attention / mlp 的投影层；显式排除 Qwen3.5 的线性注意力(GDN)与卷积参数
TARGET_CANDIDATES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    # qwen3_5 linear-attention 层常见命名（存在即挂，不存在自动跳过）
    "in_proj_qkv", "in_proj_z", "in_proj_a", "in_proj_b", "out_proj",
]
EXCLUDE_SUBSTR = ("a_log", "dt_bias", "convolution", "conv1d", "vision", "visual")


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--stage", choices=list(PRESETS), default="re")
    ap.add_argument("--out", default=None)
    ap.add_argument("--ctx", type=int, default=None)
    ap.add_argument("--epochs", type=float, default=None)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--bs", type=int, default=1)
    ap.add_argument("--ga", type=int, default=None)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--lora-r", type=int, default=None)
    ap.add_argument("--lora-alpha", type=int, default=None)
    ap.add_argument("--no-4bit", action="store_true")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--save-steps", type=int, default=50,
                    help="每 N 步存一次 checkpoint（防 BSOD/断电丢进度；0=按 epoch）")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def discover_targets(model):
    """返回实际存在的 target 模块名集合 + 命中计数（用于诊断命名差异）"""
    import torch.nn as nn
    names, hits = set(), {}
    for name, mod in model.named_modules():
        if not isinstance(mod, nn.Linear) or not name:
            continue
        leaf = name.split(".")[-1]
        if any(s in name for s in EXCLUDE_SUBSTR):
            continue
        if leaf in TARGET_CANDIDATES:
            names.add(leaf)
            hits[leaf] = hits.get(leaf, 0) + 1
    return sorted(names), hits


def main():
    a = parse()
    p = PRESETS[a.stage]
    ctx = a.ctx or p["ctx"]
    ga = a.ga or p["ga"]
    lr = a.lr if a.lr is not None else p["lr"]
    r = a.lora_r or p["r"]
    alpha = a.lora_alpha or p["alpha"]
    epochs = a.epochs if a.epochs is not None else p["epochs"]
    out = a.out or os.path.join(TRAIN_ROOT, "out", f"oxcoder9b-{a.stage}")

    if not os.path.isdir(a.base):
        sys.exit(f"[FATAL] 基座不存在: {a.base}")
    if not os.path.isfile(a.data):
        sys.exit(f"[FATAL] 数据不存在: {a.data}")

    import torch
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30 if torch.cuda.is_available() else 0
    w_gb = 9e9 * (0.5 if not a.no_4bit else 2) / 2**30

    with open(a.data, "r", encoding="utf-8") as f:
        n_samples = sum(1 for line in f if line.strip())

    print("=" * 62)
    print(f"base      = {a.base}")
    print(f"data      = {a.data}  ({n_samples} 条)")
    print(f"stage     = {a.stage}  → ctx={ctx} r={r} alpha={alpha} lr={lr} ep={epochs} ga={ga}")
    print(f"out       = {out}")
    print(f"VRAM      = {vram:.1f} GiB   权重估算 = {w_gb:.1f} GiB ({'4bit' if not a.no_4bit else 'bf16'})")
    act = 2.2 if ctx <= 2048 else 3.6
    print(f"激活估算  = {act:.1f} GiB (ctx={ctx}, gc on)")
    print(f"预算合计  = {w_gb + act + 0.9:.1f} GiB  / {vram:.1f} GiB")
    if w_gb + act + 0.9 > vram * 0.94:
        print("[WARN] 预算贴近上限 → 先降 ctx 或改 --no-4bit 关掉（关掉反而更吃显存，仅诊断用）")
    print("=" * 62)
    if a.dry_run:
        print("[dry-run] 退出")
        return

    from transformers import (
        AutoConfig, AutoModelForImageTextToText, AutoModelForCausalLM,
        AutoTokenizer, BitsAndBytesConfig,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset
    from trl import SFTTrainer, SFTConfig

    bnb = None if a.no_4bit else BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    cfg = AutoConfig.from_pretrained(a.base, trust_remote_code=True)
    arch = (getattr(cfg, "architectures", None) or [""])[0]
    loader = AutoModelForImageTextToText if "ConditionalGeneration" in arch else AutoModelForCausalLM
    print(f"[load] arch={arch or '?'} loader={loader.__name__}")

    model = loader.from_pretrained(
        a.base, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0}, trust_remote_code=True,
    )
    if not a.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.config.use_cache = False

    targets, hits = discover_targets(model)
    if not targets:
        sys.exit("[FATAL] 未探测到任何 target 模块 —— 该基座 Linear 命名不在候选表内，"
                 "先跑 --dry-run 前的命中诊断或把命名加进 TARGET_CANDIDATES")
    print(f"[lora] targets = {targets}")
    print(f"[lora] 命中数   = {hits}")

    model = get_peft_model(model, LoraConfig(
        r=r, lora_alpha=alpha, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM", target_modules=targets,
    ))
    model.print_trainable_parameters()

    ds = load_dataset("json", data_files=a.data, split="train")
    keep = {"messages"}

    def to_text(ex):
        msgs = ex.get("messages") or []
        if not msgs and "instruction" in ex:
            msgs = [{"role": "user", "content": ex["instruction"]},
                    {"role": "assistant", "content": ex["output"]}]
        return {"text": tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)}

    ds = ds.map(to_text, remove_columns=[c for c in ds.column_names if c not in keep and c != "text"])
    if "meta" in ds.column_names:
        ds = ds.remove_columns(["meta"])

    args = SFTConfig(
        output_dir=out,
        num_train_epochs=epochs,
        max_steps=a.max_steps,
        per_device_train_batch_size=a.bs,
        gradient_accumulation_steps=ga,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=lr,
        lr_scheduler_type="cosine",
        warmup_steps=10,          # trl 1.16 的 SFTConfig 已无 warmup_ratio
        dataset_text_field="text",
        bf16=True, fp16=False,
        optim="paged_adamw_8bit",
        max_length=ctx,
        # Qwen3.5 的 linear_attention 在 packing 时要求 causal_conv1d 才能分隔序列；
        # 未装该扩展时 SFTTrainer 会抛 ValueError。690-2000 条量级不需要 packing。
        packing=False,
        logging_steps=5,
        save_strategy="steps" if a.save_steps > 0 else ("epoch" if a.max_steps < 0 else "no"),
        save_steps=a.save_steps if a.save_steps > 0 else 500,
        save_total_limit=3,
        report_to="none",
        resume_from_checkpoint=a.resume,
    )

    trainer = SFTTrainer(model=model, args=args, train_dataset=ds, processing_class=tok)
    trainer.train(resume_from_checkpoint=a.resume)
    trainer.save_model(os.path.join(out, "final"))
    tok.save_pretrained(os.path.join(out, "final"))
    print(f"[OK] adapter → {os.path.join(out, 'final')}")


if __name__ == "__main__":
    main()
