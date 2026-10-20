#!/usr/bin/env python
"""train_qlora.py —— QLoRA 后训练（根目录版，路径全部在 train\\ 内）

用法:
  python train_qlora.py --size 8b  --max-steps 100          # 冒烟
  python train_qlora.py --size 8b  --epochs 3               # 正式
  python train_qlora.py --size 27b --ctx 512 --ga 32        # 27B（CPU offload，慢）
  python train_qlora.py --size 27b --dry-run                # 只打印配置与显存估算

数据格式（train\\data\\train.jsonl，每行一条）:
  {"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
  或  {"instruction":"...","output":"..."}
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

BASE = {
    "8b":  os.path.join(TRAIN_ROOT, "base", "Qwen3-8B"),
    "27b": os.path.join(TRAIN_ROOT, "base", "Qwen3.8-27B"),
}
# 只挂 Transformer 的 Linear；禁止挂 SSM 参数(gdn/a_log,dt_bias,convolution) 与 vision
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=["8b", "27b"], default="8b")
    ap.add_argument("--base", default=None, help="覆盖基座目录")
    ap.add_argument("--data", default=os.path.join(TRAIN_ROOT, "data", "train.jsonl"))
    ap.add_argument("--out", default=os.path.join(TRAIN_ROOT, "out"))
    ap.add_argument("--ctx", type=int, default=None, help="序列长度（默认 8b=2048, 27b=512）")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--bs", type=int, default=1)
    ap.add_argument("--ga", type=int, default=None, help="梯度累积（默认 8b=16, 27b=32）")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--no-4bit", action="store_true", help="关掉 4bit（bf16 LoRA，显存需求暴涨）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", default=None)
    return ap.parse_args()


def ram_weights_gb():
    """粗略读系统内存，用于 27B offload 可行性提示"""
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEMORYSTATUSEX(); m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys / 2**30, m.ullAvailPhys / 2**30
    except Exception:
        return None, None


def main():
    a = parse()
    base = a.base or BASE[a.size]
    ctx = a.ctx or (2048 if a.size == "8b" else 512)
    ga = a.ga or (16 if a.size == "8b" else 32)

    if not os.path.isdir(base):
        print(f"[FATAL] 基座不存在: {base}")
        print(f"        先跑: python scripts\\fetch_base.py --size {a.size}")
        sys.exit(1)
    if not os.path.isfile(a.data):
        print(f"[FATAL] 数据不存在: {a.data}")
        print('        每行一条: {"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}')
        sys.exit(1)

    import torch
    n_params_gb = {"8b": 8e9, "27b": 27e9}[a.size]
    w_gb = n_params_gb * (0.5 if not a.no_4bit else 2) / 2**30
    tot_ram, avail_ram = ram_weights_gb()
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30 if torch.cuda.is_available() else 0

    print("=" * 60)
    print(f"base        = {base}")
    print(f"data        = {a.data}")
    print(f"out         = {a.out}")
    print(f"size/ctx    = {a.size} / {ctx}")
    print(f"bs x ga     = {a.bs} x {ga}  (有效 batch {a.bs*ga})")
    print(f"epochs      = {a.epochs}   max_steps = {a.max_steps}")
    print(f"lora        = r={a.lora_r} alpha={a.lora_alpha}  targets={len(TARGET_MODULES)}")
    print(f"4bit        = {not a.no_4bit}")
    print(f"VRAM        = {vram:.1f} GiB")
    print(f"RAM         = {tot_ram:.1f} GiB (avail {avail_ram:.1f})" if tot_ram else "RAM         = n/a")
    print(f"权重估算    = {w_gb:.1f} GiB  ({'4bit' if not a.no_4bit else 'bf16'})")
    if w_gb > vram:
        print(f"[WARN] 权重 {w_gb:.1f} > VRAM {vram:.1f} → 必须 device_map=auto 溢出到 CPU，单步会显著变慢")
    if w_gb > (avail_ram or 0):
        print(f"[WARN] 权重 {w_gb:.1f} > 可用内存 {avail_ram:.1f} → 可能 OOM，考虑换 8B 或加虚拟内存")
    print("=" * 60)

    if a.dry_run:
        print("[dry-run] 退出")
        return

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from datasets import load_dataset
    from trl import SFTTrainer, SFTConfig

    bnb = None
    if not a.no_4bit:
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )

    print("[load] tokenizer")
    tok = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    print("[load] model（首次加载较慢，27B offload 可能 2-5 分钟）")
    model = AutoModelForCausalLM.from_pretrained(
        base,
        quantization_config=bnb,
        dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    if not a.no_4bit:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    model = get_peft_model(model, LoraConfig(
        r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM", target_modules=TARGET_MODULES,
    ))
    model.print_trainable_parameters()

    print("[data] load")
    ds = load_dataset("json", data_files=a.data, split="train")
    print(f"   samples = {len(ds)}")

    def to_text(ex):
        if "messages" in ex and ex["messages"]:
            return {"text": tok.apply_chat_template(ex["messages"], tokenize=False, add_generation_prompt=False)}
        if "instruction" in ex and "output" in ex:
            msgs = [{"role": "user", "content": ex["instruction"]},
                    {"role": "assistant", "content": ex["output"]}]
            return {"text": tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)}
        return {"text": ex.get("text", "")}

    ds = ds.map(to_text, remove_columns=[c for c in ds.column_names if c != "text"])

    args = SFTConfig(
        output_dir=a.out,
        num_train_epochs=a.epochs,
        max_steps=a.max_steps,
        per_device_train_batch_size=a.bs,
        gradient_accumulation_steps=ga,
        gradient_checkpointing=True,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        logging_steps=5,
        logging_dir=os.path.join(TRAIN_ROOT, "logs"),
        save_strategy="epoch" if a.max_steps < 0 else "no",
        save_total_limit=2,
        optim="paged_adamw_8bit",
        max_grad_norm=0.3,
        report_to="none",
        max_length=ctx,
        dataset_text_field="text",
        resume_from_checkpoint=a.resume,
    )

    trainer = SFTTrainer(model=model, args=args, train_dataset=ds, tokenizer=tok)
    print("[train] start")
    trainer.train()

    adapter = os.path.join(a.out, "adapter")
    model.save_pretrained(adapter)
    tok.save_pretrained(adapter)
    print(f"[done] adapter -> {adapter}")
    print("下一步: python scripts\\merge.py --size", a.size)


if __name__ == "__main__":
    main()
