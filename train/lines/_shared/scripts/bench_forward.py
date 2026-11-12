#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练前速度/显存基准 —— 不训练，只测 forward / forward+backward

用途：
  1. 确认 ctx 9216 下能不能跑（显存是否够）
  2. 拿到真实单步耗时，用于估算总训练时长
  3. 排除 attn backend / fla kernel 是否生效

用法：
  # 只测 forward（最安全，不占梯度显存）
  python bench_forward.py --ctx 9216 --mode fwd

  # 测 forward + backward（会占梯度显存，但仍不 step 参数）
  python bench_forward.py --ctx 9216 --mode fwd-bwd

  # 扫多个 ctx
  python bench_forward.py --sweep 2048,4096,8192,9216 --mode fwd
"""

import argparse
import gc
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import torch

MODEL = "train/lines/9b-oxcoder/models/OxCoder-9B"
GIB = 2 ** 30


def log(msg):
    print(msg, flush=True)


def mem(tag=""):
    a = torch.cuda.memory_allocated() / GIB
    r = torch.cuda.max_memory_allocated() / GIB
    res = torch.cuda.memory_reserved() / GIB
    log("  [mem%s] alloc=%.2f GiB  reserved=%.2f GiB  peak=%.2f GiB" % ((" " + tag) if tag else "", a, res, r))


def load_model(use_4bit=True, attn="sdpa"):
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    t0 = time.time()
    kw = dict(
        device_map={"": 0},
        low_cpu_mem_usage=True,
        attn_implementation=attn,
    )
    if use_4bit:
        kw["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    model = AutoModelForCausalLM.from_pretrained(MODEL, **kw)
    log("模型加载 %.1f s, 参数量 %.2f B" % (time.time() - t0, sum(p.numel() for p in model.parameters()) / 1e9))
    mem("加载后")
    return model


def bench(model, ctx, mode, warmup=1, iters=2):
    dev = next(model.parameters()).device
    ids = torch.randint(0, 30000, (1, ctx), device=dev, dtype=torch.long)
    attn = torch.ones_like(ids)

    torch.cuda.reset_peak_memory_stats()
    # warmup
    for _ in range(warmup):
        out = model(input_ids=ids, attention_mask=attn)
        del out
        torch.cuda.empty_cache()

    times = []
    for i in range(iters):
        torch.cuda.synchronize()
        t0 = time.time()
        if mode == "fwd":
            with torch.no_grad():
                out = model(input_ids=ids, attention_mask=attn)
            del out
        else:
            model.zero_grad(set_to_none=True)
            out = model(input_ids=ids, attention_mask=attn)
            loss = out.logits.float().mean()
            loss.backward()
            del out, loss
        torch.cuda.synchronize()
        dt = time.time() - t0
        times.append(dt)
        log("  iter%d %.2f s" % (i + 1, dt))

    del ids, attn
    gc.collect()
    torch.cuda.empty_cache()
    return {"ctx": ctx, "mode": mode, "sec": round(sum(times) / len(times), 2), "iters": iters}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", type=int, default=9216)
    ap.add_argument("--sweep", default=None, help="逗号分隔的 ctx 列表")
    ap.add_argument("--mode", default="fwd", choices=["fwd", "fwd-bwd"])
    ap.add_argument("--no-4bit", dest="no4bit", action="store_true")
    ap.add_argument("--report", default="train/lines/9b-oxcoder/data/_legacy/_bench-forward.json")
    args = ap.parse_args()

    log("torch %s / cuda %s" % (torch.__version__, torch.version.cuda))
    log("GPU %s, total %.2f GiB" % (torch.cuda.get_device_name(0), torch.cuda.get_device_properties(0).total_memory / GIB))

    model = load_model(use_4bit=not args.no4bit)
    model.eval()
    if args.mode == "fwd-bwd":
        model.train()

    ctxs = [int(x) for x in args.sweep.split(",")] if args.sweep else [args.ctx]
    results = []
    for c in ctxs:
        log("")
        log("=== ctx %d / mode %s ===" % (c, args.mode))
        try:
            r = bench(model, c, args.mode)
            r["ok"] = True
            r["peak_gib"] = round(torch.cuda.max_memory_allocated() / GIB, 2)
            results.append(r)
            log("  → 平均 %.2f s, 峰值 %.2f GiB" % (r["sec"], r["peak_gib"]))
        except torch.cuda.OutOfMemoryError as e:
            log("  → OOM: %s" % str(e)[:160])
            results.append({"ctx": c, "mode": args.mode, "ok": False, "err": "OOM"})
            torch.cuda.empty_cache()
        except Exception as e:
            log("  → ERR %s: %s" % (type(e).__name__, str(e)[:200]))
            results.append({"ctx": c, "mode": args.mode, "ok": False, "err": type(e).__name__})
            torch.cuda.empty_cache()

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log("")
    log("报告 → %s" % args.report)
    for r in results:
        if r.get("ok"):
            log("  ctx %-6d %-8s %6.2f s  峰值 %.2f GiB" % (r["ctx"], r["mode"], r["sec"], r["peak_gib"]))
        else:
            log("  ctx %-6d %-8s FAIL %s" % (r["ctx"], r["mode"], r.get("err")))


if __name__ == "__main__":
    main()
