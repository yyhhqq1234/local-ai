#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forward profile —— 分解各算子耗时占比

目的：确认 8 层 full attention（head_dim 256，只能走 mem_efficient）
      到底占 forward 总时间多少，决定是否值得折腾 xformers / flash-attn。

用法：
  python profile_forward.py --ctx 2048
  python profile_forward.py --ctx 4096 --top 25
"""

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

import torch

MODEL = "train/lines/9b-oxcoder/models/OxCoder-9B"
GIB = 2 ** 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--top", type=int, default=22)
    ap.add_argument("--iters", type=int, default=2)
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    print("loading...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL,
        device_map={"": 0},
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        ),
    )
    model.eval()
    print("loaded, alloc %.2f GiB" % (torch.cuda.memory_allocated() / GIB), flush=True)

    ids = torch.randint(0, 30000, (1, args.ctx), device="cuda", dtype=torch.long)
    attn = torch.ones_like(ids)

    # warmup
    with torch.no_grad():
        model(input_ids=ids, attention_mask=attn)
    torch.cuda.synchronize()

    from torch.profiler import ProfilerActivity, profile

    with profile(activities=[ProfilerActivity.CUDA, ProfilerActivity.CPU]) as prof:
        with torch.no_grad():
            for _ in range(args.iters):
                o = model(input_ids=ids, attention_mask=attn)
                del o
        torch.cuda.synchronize()

    print()
    print("=" * 78)
    print("TOP %d op by CUDA time (ctx=%d, iters=%d)" % (args.top, args.ctx, args.iters))
    print("=" * 78)
    print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=args.top))

    # 按类别聚合
    import re

    cats = {
        "full_attn (SDPA)": 0.0,
        "linear_attn (fla)": 0.0,
        "conv1d": 0.0,
        "matmul/gemm": 0.0,
        "lm_head/logits": 0.0,
        "norm/elementwise": 0.0,
        "other": 0.0,
    }
    total = 0.0
    for ev in prof.key_averages():
        t = ev.self_device_time_total or 0.0
        if t <= 0:
            continue
        total += t
        n = ev.key.lower()
        if "attention" in n or "sdpa" in n or "flash" in n or "efficient" in n or "cutlass" in n:
            cats["full_attn (SDPA)"] += t
        elif "gated_delta" in n or "delta_rule" in n or "chunk" in n or "recurrent" in n or "wy_fast" in n or "l2norm" in n:
            cats["linear_attn (fla)"] += t
        elif "conv" in n:
            cats["conv1d"] += t
        elif "gemm" in n or "matmul" in n or "addmm" in n or "mm" == n or "bmm" in n:
            cats["matmul/gemm"] += t
        elif "lm_head" in n or "logits" in n or "vocab" in n:
            cats["lm_head/logits"] += t
        elif any(k in n for k in ("norm", "rms", "silu", "mul", "add", "copy", "cast", "elementwise")):
            cats["norm/elementwise"] += t
        else:
            cats["other"] += t

    print()
    print("=" * 78)
    print("按类别聚合（self CUDA time）")
    print("=" * 78)
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        if total > 0 and v > 0:
            print("  %-22s %8.1f ms  %5.1f%%" % (k, v / 1000, v / total * 100))
    print("  %-22s %8.1f ms" % ("TOTAL", total / 1000))


if __name__ == "__main__":
    main()
