#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练真实路径基准：prepare + 全转 bf16 + hidden-only（不产 logits）

对应 LigerSFTTrainer 的实际计算路径：只调 text model 拿 last_hidden_state，
再在外部做分块 CE —— 从源头不产生 [B,T,vocab] 的 logits 张量。

用途：确定在「fp32→bf16 修复」之后，ctx 能上到多少。

用法：
  python bench_hidden.py --sweep 4096,8192,9216 --mode fwd
  python bench_hidden.py --sweep 8192,9216 --mode fwd-bwd --ckpt
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


def find_text_model(model):
    """找 text model。

    Qwen3_5 结构：Qwen3_5ForConditionalGeneration.model -> Qwen3_5Model
                  Qwen3_5Model.layers / .norm / .embed_tokens / .rotary_emb
    被 peft 包一层后路径变成 base_model.model.model。
    """
    # 1) 优先按名字约定
    for n, m in model.named_modules():
        if n.endswith("language_model") or n.endswith("text_model"):
            return m, n

    # 2) 顶层 child 名为 model，且本身不是 ForConditionalGeneration
    for n, m in model.named_children():
        if n == "model" and not type(m).__name__.endswith("ForConditionalGeneration"):
            return m, n

    # 3) 递归找最后一个 .model（排除 self）
    cand = None
    for n, m in model.named_modules():
        if n.endswith(".model") and not type(m).__name__.endswith("ForConditionalGeneration"):
            if hasattr(m, "layers"):
                cand = (m, n)
    if cand:
        return cand
    return None, None


def mem_str():
    return "alloc=%.2f reserved=%.2f peak=%.2f GiB" % (
        torch.cuda.memory_allocated() / GIB,
        torch.cuda.memory_reserved() / GIB,
        torch.cuda.max_memory_allocated() / GIB,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="4096,8192,9216")
    ap.add_argument("--mode", default="fwd", choices=["fwd", "fwd-bwd"])
    ap.add_argument("--ckpt", action="store_true", help="开 gradient checkpointing")
    ap.add_argument("--cast-bf16", dest="cast", action="store_true", default=True)
    ap.add_argument("--no-cast", dest="cast", action="store_false")
    ap.add_argument("--report", default="train/lines/9b-oxcoder/data/_legacy/_bench-hidden.json")
    args = ap.parse_args()

    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    from peft import prepare_model_for_kbit_training

    print("torch %s / cuda %s / GPU %s" % (
        torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0)), flush=True)

    t0 = time.time()
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
    print("加载 %.1f s  %s" % (time.time() - t0, mem_str()), flush=True)

    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=args.ckpt)
    print("prepare 后  %s" % mem_str(), flush=True)

    if args.cast:
        n = 0
        for p in model.parameters():
            if p.dtype == torch.float32:
                p.data = p.data.to(torch.bfloat16)
                n += 1
        torch.cuda.synchronize()
        print("转 bf16 %d 个参数  %s" % (n, mem_str()), flush=True)

    text, tname = find_text_model(model)
    print("text model = %s" % tname, flush=True)
    if text is None:
        sys.exit("找不到 text model")

    if args.ckpt:
        # 只对 text model 开 checkpoint，避免 lm_head 干扰
        text.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        print("gradient checkpointing: on (non-reentrant)", flush=True)

    # 让计算图有梯度：kbit 训练会把全部参数冻死，没有 LoRA 时 hidden 无 grad_fn，
    # 无 ckpt 的情况下 backward 会报 "element 0 does not require grad"。
    fake = None
    for n, p in text.named_parameters():
        if p.dtype == torch.bfloat16:
            p.requires_grad_(True)
            fake = n
            print("fake-trainable: %s  shape=%s  (只为测速，不改变数值)" % (n, tuple(p.shape)), flush=True)
            break
    if fake is None:
        print("WARN: 没有可训练的 bf16 参数，backward 可能失败", flush=True)

    model.train() if args.mode == "fwd-bwd" else model.eval()

    results = []
    for ctx in [int(x) for x in args.sweep.split(",")]:
        print("", flush=True)
        print("=== ctx %d / %s / ckpt=%s ===" % (ctx, args.mode, args.ckpt), flush=True)
        ids = torch.randint(0, 30000, (1, ctx), device="cuda", dtype=torch.long)
        am = torch.ones_like(ids)
        torch.cuda.reset_peak_memory_stats()
        try:
            # warmup
            with torch.no_grad():
                o = text(input_ids=ids, attention_mask=am)
                del o
            torch.cuda.empty_cache()

            ts = []
            for i in range(3):
                torch.cuda.synchronize()
                t = time.time()
                if args.mode == "fwd":
                    with torch.no_grad():
                        o = text(input_ids=ids, attention_mask=am)
                    del o
                else:
                    model.zero_grad(set_to_none=True)
                    o = text(input_ids=ids, attention_mask=am)
                    h = o.last_hidden_state
                    loss = h.float().mean()
                    loss.backward()
                    del o, h, loss
                torch.cuda.synchronize()
                dt = time.time() - t
                ts.append(dt)
                print("  iter%d %.2f s  %s" % (i + 1, dt, mem_str()), flush=True)

            avg = sum(ts) / len(ts)
            peak = torch.cuda.max_memory_allocated() / GIB
            results.append({"ctx": ctx, "mode": args.mode, "ckpt": args.ckpt,
                            "cast_bf16": args.cast, "sec": round(avg, 2),
                            "peak_gib": round(peak, 2), "ok": True})
            print("  → 平均 %.2f s，峰值 %.2f GiB" % (avg, peak), flush=True)
        except torch.cuda.OutOfMemoryError as e:
            print("  → OOM: %s" % str(e)[:150], flush=True)
            results.append({"ctx": ctx, "mode": args.mode, "ckpt": args.ckpt,
                            "cast_bf16": args.cast, "ok": False, "err": "OOM"})
        except Exception as e:
            print("  → ERR %s: %s" % (type(e).__name__, str(e)[:200]), flush=True)
            results.append({"ctx": ctx, "mode": args.mode, "ckpt": args.ckpt,
                            "cast_bf16": args.cast, "ok": False, "err": type(e).__name__})
        finally:
            del ids, am
            gc.collect()
            torch.cuda.empty_cache()

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("")
    print("=" * 66)
    for r in results:
        if r.get("ok"):
            print("  ctx %-6d %-8s ckpt=%-5s bf16=%-5s %6.2f s  峰值 %5.2f GiB" % (
                r["ctx"], r["mode"], r["ckpt"], r["cast_bf16"], r["sec"], r["peak_gib"]))
        else:
            print("  ctx %-6d %-8s ckpt=%-5s bf16=%-5s FAIL %s" % (
                r["ctx"], r["mode"], r["ckpt"], r["cast_bf16"], r.get("err")))
    print("报告 → %s" % args.report)


if __name__ == "__main__":
    main()
