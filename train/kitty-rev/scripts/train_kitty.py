#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""train_kitty.py —— kitty 逆向工作台能力后训练（SFT → 可选 DPO）

与 train/scripts/train_qlora.py 的差别：
  · 数据默认取 kitty-rev/data/{train,eval}.jsonl（真实契约 + 真实轨迹 + 手写行为种子）
  · 支持 --stage dpo：在 SFT adapter 之上再跑一轮 DPO（偏好对 data/dpo.jsonl）
  · LoRA 挂载红线写死在此（Qwen3_5 架构挂到 gdn.* 直接 NaN）
  · 训练前打印数据体检（类别分布 / 长度分布），不合规直接退出，不浪费一次加载

用法:
  python train_kitty.py --size 8b --dry-run                # 体检 + 显存估算
  python train_kitty.py --size 8b --max-steps 100          # 冒烟
  python train_kitty.py --size 8b --epochs 3               # 正式 SFT
  python train_kitty.py --size 27b --ctx 512 --ga 32       # 27B（offload）
  python train_kitty.py --size 8b --stage dpo --sft-adapter out/adapter
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # train/kitty-rev
TRAIN_ROOT = os.path.dirname(HERE)                                   # train/
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(TRAIN_ROOT, "hf"))
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE = {
    "8b": os.path.join(TRAIN_ROOT, "base", "Qwen3-8B"),
    "27b": os.path.join(TRAIN_ROOT, "base", "Qwen3.8-27B"),
}

# 红线：只挂 Transformer 的 7 个 Linear。
# 禁止 gdn/a_log、gdn/dt_bias、gdn/convolution、gdn/a_projection、gdn/b_projection、gdn/norm、vision.*
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]

# 训练集里必须出现的类别（缺一类就说明数据构造没跑全）
REQUIRED_CATS = ["real-trajectory", "op-syntax", "tool-route", "kb-re", "kb-tool"]


def _trainer(cls, **kw):
    """trl 1.16 起 tokenizer= 改名 processing_class=；两种都试，报错信息保留。"""
    tok = kw.pop("tokenizer", None)
    try:
        return cls(**kw, tokenizer=tok) if tok is not None else cls(**kw)
    except TypeError as e:
        if tok is not None and "tokenizer" in str(e):
            print("[cfg] 该 trl 已弃用 tokenizer=，改用 processing_class=")
            return cls(**kw, processing_class=tok)
        raise


def _build_args(cls, **desired):
    """按目标 config 类签名过滤参数：trl/transformers 版本间会删改字段（如 warmup_ratio/logging_dir）。"""
    import inspect
    ok = set(inspect.signature(cls.__init__).parameters)
    kept, dropped = {}, []
    for k, v in desired.items():
        if k in ok:
            kept[k] = v
        else:
            dropped.append(k)
    if dropped:
        print(f"[cfg] {cls.__name__} 不支持 {dropped}，已跳过")
    return cls(**kept)


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", choices=["8b", "27b"], default="8b")
    ap.add_argument("--base", default=None)
    ap.add_argument("--data", default=os.path.join(HERE, "data", "large", "train.jsonl"))
    ap.add_argument("--eval-data", default=os.path.join(HERE, "data", "large", "eval.jsonl"))
    ap.add_argument("--dpo-data", default=os.path.join(HERE, "data", "large", "dpo.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--stage", choices=["sft", "dpo"], default="sft")
    ap.add_argument("--sft-adapter", default=None, help="stage=dpo 时的 SFT adapter 目录")
    ap.add_argument("--ctx", type=int, default=None)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--bs", type=int, default=1)
    ap.add_argument("--ga", type=int, default=None)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--no-4bit", action="store_true")
    ap.add_argument("--max-memory", default="", help='形如 "cuda:0=10GiB,cpu=24GiB"；27B 4bit offload 必填')
    ap.add_argument("--cpu-offload", action="store_true", help="4bit 允许 CPU/磁盘 offload（llm_int8_enable_fp32_cpu_offload）")
    ap.add_argument("--text-only", action="store_true", help="VL 包装模型只加载文本塔（config.language_model_only=True）")
    ap.add_argument("--all-gpu", action="store_true", help='强制 device_map={"": 0}（全放 GPU，不触发 accelerate offload 钩子）')
    ap.add_argument("--gpu-layers", type=int, default=0,
                    help="部分层 4bit 放 GPU，其余层保持 bf16 驻 CPU（offload 不量化路线）")
    ap.add_argument("--layer-prefix", default="model.language_model.layers",
                    help="层模块名前缀（text-only 加载可能是 model.layers）")
    ap.add_argument("--skip-kbit-prepare", action="store_true",
                    help="跳过 peft.prepare_model_for_kbit_training 的全局 fp32 upcast（offload 场景会 OOM）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume", default=None)
    return ap.parse_args()


def load_jsonl(p):
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[FATAL] {os.path.basename(p)}:{i} JSON 坏了：{e}")
                sys.exit(2)
    return rows


def check_sft(path):
    rows = load_jsonl(path)
    cats = {}
    lens = []
    bad = 0
    for r in rows:
        m = r.get("messages") or []
        if len(m) < 2 or m[-1].get("role") != "assistant":
            bad += 1
            continue
        cats[(r.get("meta") or {}).get("cat", "?")] = cats.get((r.get("meta") or {}).get("cat", "?"), 0) + 1
        lens.append(sum(len(str(x.get("content", ""))) for x in m))
    print(f"[data] {os.path.basename(path)}: rows={len(rows)} bad(末条非 assistant)={bad}")
    print("       类别: " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items(), key=lambda x: -x[1])[:8]))
    if lens:
        lens.sort()
        print(f"       字符数 p50={lens[len(lens)//2]} p90={lens[int(len(lens)*0.9)]} max={lens[-1]}")
    miss = [c for c in REQUIRED_CATS if c not in cats]
    if miss:
        print(f"[FATAL] 缺类别 {miss}；先跑 python scripts/harvest_sessions.py && python scripts/build_dataset.py")
        sys.exit(3)
    return rows


def check_dpo(path):
    rows = load_jsonl(path)
    bad = [i for i, r in enumerate(rows, 1) if not all(k in r for k in ("prompt", "chosen", "rejected"))]
    print(f"[data] {os.path.basename(path)}: pairs={len(rows)} bad={len(bad)}")
    if bad:
        print(f"[FATAL] 第 {bad[:5]} 行缺 prompt/chosen/rejected")
        sys.exit(3)
    return rows


def main():
    a = parse()
    if a.stage == "sft":
        check_sft(a.data)
        if os.path.isfile(a.eval_data):
            check_sft(a.eval_data)
    else:
        check_dpo(a.dpo_data)

    base = a.base or BASE[a.size]
    ctx = a.ctx or (2048 if a.size == "8b" else 512)
    ga = a.ga or (16 if a.size == "8b" else 32)

    if not os.path.isdir(base):
        print(f"[FATAL] 基座不存在: {base}")
        print(f"        先跑: python ../scripts/fetch_base.py --size {a.size}")
        sys.exit(1)
    if a.stage == "dpo" and not a.sft_adapter:
        print("[FATAL] stage=dpo 需要 --sft-adapter <SFT 产出的 adapter 目录>")
        sys.exit(1)

    import torch
    n_params = {"8b": 8e9, "27b": 27e9}[a.size]
    w_gb = n_params * (0.5 if not a.no_4bit else 2) / 2 ** 30
    vram = torch.cuda.get_device_properties(0).total_memory / 2 ** 30 if torch.cuda.is_available() else 0

    print("=" * 64)
    print(f"stage       = {a.stage}")
    print(f"base        = {base}")
    print(f"data        = {a.data if a.stage == 'sft' else a.dpo_data}")
    print(f"out         = {a.out}")
    print(f"size/ctx    = {a.size} / {ctx}    bs x ga = {a.bs} x {ga}")
    print(f"lora        = r={a.lora_r} alpha={a.lora_alpha} targets={TARGET_MODULES}")
    print(f"4bit        = {not a.no_4bit}   VRAM = {vram:.1f} GiB   权重估算 = {w_gb:.1f} GiB")
    if w_gb > vram:
        print("[WARN] 权重 > VRAM → device_map=auto 溢出到 CPU，单步显著变慢（27B 属正常）")
    print("=" * 64)

    if a.dry_run:
        print("[dry-run] 退出（未加载模型）")
        return

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training, PeftModel

    bnb = None
    if not a.no_4bit:
        kw = dict(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                  bnb_4bit_compute_dtype=torch.bfloat16,
                  bnb_4bit_use_double_quant=True)
        if a.cpu_offload:
            kw["llm_int8_enable_fp32_cpu_offload"] = True
        bnb = BitsAndBytesConfig(**kw)

    tok = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    print("[load] model")
    load_kw = dict(quantization_config=bnb, dtype=torch.bfloat16,
                   device_map="auto", trust_remote_code=True)
    if a.gpu_layers:
        from transformers import AutoConfig as _AC2
        _c = _AC2.from_pretrained(base, trust_remote_code=True)
        total = getattr(getattr(_c, "text_config", _c), "num_hidden_layers", 64)
        skip = [f"{a.layer_prefix}.{i}" for i in range(a.gpu_layers, total)] + ["visual", "vision_tower"]
        kw2 = dict(load_kw["quantization_config"].to_dict()) if hasattr(load_kw["quantization_config"], "to_dict") else {}
        from transformers import BitsAndBytesConfig as _B
        load_kw["quantization_config"] = _B(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
            llm_int8_enable_fp32_cpu_offload=True,
            llm_int8_skip_modules=skip,
        )
        dm = {"": "cpu", "lm_head": 0}
        for i in range(a.gpu_layers):
            dm[f"{a.layer_prefix}.{i}"] = 0
        load_kw["device_map"] = dm
        print(f"[load] 部分层 4bit：GPU {a.gpu_layers}/{total} 层，其余 {total-a.gpu_layers} 层保持 bf16 在 CPU")
    if a.text_only:
        from transformers import AutoConfig as _AC
        _cfg = _AC.from_pretrained(base, trust_remote_code=True)
        if hasattr(_cfg, "language_model_only"):
            _cfg.language_model_only = True
            load_kw["config"] = _cfg
            print("[load] text-only: 只加载文本塔（跳过 vision）")
    if a.all_gpu:
        load_kw["device_map"] = {"": 0}
    if a.max_memory and not a.all_gpu:
        mm = {}
        for part in a.max_memory.split(","):
            k, v = part.split("=")
            k = k.strip()
            # accelerate 只认整数（GPU 序号）/ 'cpu' / 'disk' / 'mps'；'cuda:0' 会报错
            mm[int(k) if k.isdigit() else k] = v.strip()
        load_kw["max_memory"] = mm
    model = AutoModelForCausalLM.from_pretrained(base, **load_kw)
    if not a.no_4bit:
        if a.skip_kbit_prepare:
            print("[prep] skip peft fp32 upcast（offload 场景）：手动开梯度检查点 + 冻结主干")
            try:
                model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
            except TypeError:
                model.gradient_checkpointing_enable()
            for p_ in model.parameters():
                p_.requires_grad = False
        else:
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    if a.stage == "dpo":
        print(f"[load] SFT adapter: {a.sft_adapter}")
        model = PeftModel.from_pretrained(model, a.sft_adapter, is_trainable=True)
        model.print_trainable_parameters()
    else:
        model = get_peft_model(model, LoraConfig(
            r=a.lora_r, lora_alpha=a.lora_alpha, lora_dropout=0.05, bias="none",
            task_type="CAUSAL_LM", target_modules=TARGET_MODULES))
        model.print_trainable_parameters()

    def to_text(ex):
        m = ex["messages"]
        return {"text": tok.apply_chat_template(m, tokenize=False, add_generation_prompt=False)}

    if a.stage == "sft":
        from datasets import load_dataset
        from trl import SFTTrainer, SFTConfig
        ds = load_dataset("json", data_files=a.data, split="train")
        ds = ds.map(to_text, remove_columns=[c for c in ds.column_names if c != "text"])
        print(f"[data] samples={len(ds)}")
        args = _build_args(SFTConfig,
            output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps,
            per_device_train_batch_size=a.bs, gradient_accumulation_steps=ga,
            gradient_checkpointing=True, learning_rate=a.lr, lr_scheduler_type="cosine",
            warmup_steps=10, bf16=True, logging_steps=5,
            save_strategy="epoch" if a.max_steps < 0 else "no", save_total_limit=2,
            optim="paged_adamw_8bit", max_grad_norm=0.3, report_to="none",
            max_length=ctx, dataset_text_field="text", resume_from_checkpoint=a.resume,
        )
        _trainer(SFTTrainer, model=model, args=args, train_dataset=ds, tokenizer=tok).train()
        out = os.path.join(a.out, "adapter")
    else:
        from datasets import load_dataset
        from trl import DPOTrainer, DPOConfig
        ds = load_dataset("json", data_files=a.dpo_data, split="train")
        print(f"[data] pairs={len(ds)}")
        args = _build_args(DPOConfig,
            output_dir=a.out, num_train_epochs=a.epochs, max_steps=a.max_steps,
            per_device_train_batch_size=a.bs, gradient_accumulation_steps=ga,
            gradient_checkpointing=True, learning_rate=min(a.lr, 5e-5),
            lr_scheduler_type="cosine", warmup_steps=10, bf16=True, logging_steps=1,
            save_strategy="no", optim="paged_adamw_8bit", max_grad_norm=0.3,
            report_to="none", beta=0.1, max_length=ctx, max_prompt_length=ctx // 2,
        )
        _trainer(DPOTrainer, model=model, ref_model=None, args=args, train_dataset=ds, tokenizer=tok).train()
        out = os.path.join(a.out, "adapter-dpo")

    model.save_pretrained(out)
    tok.save_pretrained(out)
    print(f"[done] adapter -> {out}")
    print("下一步: python ../scripts/merge.py --size", a.size, "  （合并后转 GGUF → ninfer converter）")


if __name__ == "__main__":
    main()
