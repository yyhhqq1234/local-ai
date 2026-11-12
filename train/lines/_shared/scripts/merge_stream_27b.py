#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""merge_stream_27b.py — 流式逐分片合并 LoRA（本机 31.5 GiB 内存可跑 27B）

为什么不用 peft 的 merge_and_unload：
  27.5B 参数在 bf16 下约 55 GiB，本机总内存 31.5 GiB（可用 16.3）→ 必 OOM。
  但 LoRA 只挂在少量 2D 权重上，可以「一个分片一个分片」处理：
    峰值内存 = 单个分片（≈3 GiB）+ 一个 LoRA 矩阵（≤0.4 GiB）

合并公式（peft 口径）：
    W' = W + (alpha / r) * (B @ A)
    A: [r, in_features]  B: [out_features, r]
    alpha=32 r=16 → scale=2.0

注意：
  · 视觉塔（visual.*）与 lm_head 无 LoRA，原样搬运（只训语言塔，视觉必须无损）
  · 输出 dtype 统一 bf16（与基座一致）
  · 支持断点续跑：已存在的输出分片跳过（--resume）

用法：
    python merge_stream_27b.py --base <基座目录> --adapter <adapter 目录> --out <输出目录>
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import torch
from safetensors import safe_open
from safetensors.torch import save_file


def load_lora(adapter_dir: str):
    """返回 {(layer_key): (A, B)}；layer_key 去掉 lora_A/B.weight 后缀"""
    p = os.path.join(adapter_dir, "adapter_model.safetensors")
    with open(os.path.join(adapter_dir, "adapter_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    r = cfg["r"]
    alpha = cfg["lora_alpha"]
    scale = alpha / r
    A, B = {}, {}
    with safe_open(p, "pt") as f:
        for k in f.keys():
            if k.endswith(".lora_A.weight"):
                A[k[: -len(".lora_A.weight")]] = f.get_tensor(k)
            elif k.endswith(".lora_B.weight"):
                B[k[: -len(".lora_B.weight")]] = f.get_tensor(k)
    pairs = {}
    for k in A:
        if k in B:
            pairs[k] = (A[k], B[k])
    print(f"[lora] r={r} alpha={alpha} scale={scale} pairs={len(pairs)}", flush=True)
    return pairs, scale


def base_key_candidates(lora_key: str):
    """LoRA 键 → 基座键的候选名（按优先级）

    实际两边的命名差两级：
      adapter: base_model.model.model.layers.0.mlp.down_proj.lora_A.weight
      基座:     model.language_model.layers.0.mlp.down_proj.weight
    多模态封装把语言塔挂在 model.language_model.* 下，且另有 mtp.layers.* / visual.*。
    """
    k = lora_key
    if k.startswith("base_model.model."):
        k = k[len("base_model.model."):]
    elif k.startswith("base_model."):
        k = k[len("base_model."):]
    stem = k + ".weight"
    cands = [stem]
    if stem.startswith("model.layers."):
        cands.append(stem.replace("model.layers.", "model.language_model.layers.", 1))
    if stem.startswith("model.") and ".layers." not in stem.split(".")[1]:
        cands.append(stem.replace("model.", "model.language_model.", 1))
    return cands


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    idx_p = os.path.join(a.base, "model.safetensors.index.json")
    with open(idx_p, encoding="utf-8") as f:
        idx = json.load(f)
    wmap = idx["weight_map"]
    shards = sorted(set(wmap.values()))
    print(f"[base] tensors={len(wmap)} shards={len(shards)}", flush=True)

    pairs, scale = load_lora(a.adapter)
    # 反查：基座 tensor 名 → lora 对（按候选名逐个试，命中以 weight_map 为准）
    base_keys = set(wmap)
    by_base = {}
    unmatched = []
    for lk, (A, B) in pairs.items():
        hitk = next((c for c in base_key_candidates(lk) if c in base_keys), None)
        if hitk is None:
            unmatched.append(lk)
            continue
        by_base[hitk] = (A, B, lk)
    print(f"[map] LoRA 对 {len(pairs)} → 命中基座 {len(by_base)}，未命中 {len(unmatched)}", flush=True)
    if unmatched:
        print(f"[map] 未命中示例：{unmatched[:3]}", flush=True)
        print(f"[map] 候选示例：{base_key_candidates(unmatched[0])}", flush=True)
        return 2
    hit = set()
    os.makedirs(a.out, exist_ok=True)

    t0 = time.time()
    for si, sh in enumerate(shards, 1):
        op = os.path.join(a.out, sh)
        if a.resume and os.path.exists(op) and os.path.getsize(op) > 0:
            print(f"[{si}/{len(shards)}] {sh} 已存在，跳过", flush=True)
            # 仍然标记命中，避免最后报"未消费"
            for tn in wmap:
                if wmap[tn] == sh and tn in by_base:
                    hit.add(tn)
            continue
        tp = os.path.join(a.base, sh)
        out = {}
        with safe_open(tp, "pt") as f:
            for tn in f.keys():
                w = f.get_tensor(tn)
                if tn in by_base:
                    A, B, lk = by_base[tn]
                    delta = (B.float() @ A.float()) * scale
                    if tuple(delta.shape) != tuple(w.shape):
                        raise SystemExit(
                            f"[FATAL] 形状不匹配 {tn}: base{tuple(w.shape)} vs delta{tuple(delta.shape)}")
                    w = (w.float() + delta).to(torch.bfloat16)
                    hit.add(tn)
                out[tn] = w.contiguous()
        save_file(out, op, metadata={"format": "pt"})
        del out
        el = time.time() - t0
        print(f"[{si}/{len(shards)}] {sh} → {os.path.getsize(op)/2**30:.2f} GiB  "
              f"累计 {el/60:.1f} min", flush=True)

    miss = set(by_base) - hit
    if miss:
        print(f"[warn] {len(miss)} 个 LoRA 目标未在基座中命中，例：{list(miss)[:5]}", flush=True)
        return 2
    print(f"[done] 全部分片合并完成，用时 {(time.time()-t0)/60:.1f} min；LoRA 命中 {len(hit)}", flush=True)

    # 配置 / tokenizer / 索引原样复制（转换脚本要用）
    for fn in os.listdir(a.base):
        if fn.endswith(".safetensors") or fn.endswith(".safetensors.index.json"):
            continue
        src = os.path.join(a.base, fn)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(a.out, fn))
    # 重写 index（键名不变，只改 shard 归属——与基座一致，直接复制即可）
    shutil.copy2(idx_p, os.path.join(a.out, "model.safetensors.index.json"))
    print("[done] 配置与索引已复制", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
