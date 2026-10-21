#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""split_model_layers.py —— 把 HF safetensors 基座拆成「每层一个文件」

目的：让 12 GB 显卡的机器不必整体驻留 27B，只按需加载要训的层。

输出结构（<out>/）：
    embed.safetensors            # model.language_model.embed_tokens.*
    layer_00.safetensors ...     # model.language_model.layers.N.*  每层一个
    tail.safetensors             # model.language_model.norm.* / lm_head.* / 其他非层参数
    layers_index.json            # 每个文件含哪些 key、字节数、张量数、sha256(前 16 hex)

内存特性：逐张量 get_tensor → 逐层聚合 → 落盘 → 释放，峰值 ≈ 单层大小（27B/64 ≈ 0.84 GiB）+ 一个 shard 页缓存。

用法：
    python split_model_layers.py --src train/base/Qwen3.8-27B --out train/base/Qwen3.8-27B-layers
    python split_model_layers.py --src ... --out ... --dry-run     # 只统计不落盘
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

import torch
from safetensors import safe_open
from safetensors.torch import save_file

LAYER_RE = re.compile(r"^(?P<prefix>.+?\.layers\.)(?P<idx>\d+)\.(?P<rest>.+)$")


def human(n):
    return f"{n / 2 ** 30:.2f} GiB" if n >= 2 ** 30 else f"{n / 2 ** 20:.1f} MiB"


def classify(key):
    """返回 (group, layer_idx)：group ∈ {'embed','layer','head','visual','other'}"""
    # 必须先排除 mtp.*：`mtp.layers.0.*` 会被 LAYER_RE 误匹配成 layer 0，
    # 导致 layer_00 里混进 MTP 头权重（deliver-prep 2026-10-21 实测发现：14 个张量）。
    if key.startswith("mtp.") or ".mtp." in key:
        return "other", None
    m = LAYER_RE.match(key)
    if m:
        return "layer", int(m.group("idx"))
    if ".embed_tokens" in key:
        return "embed", None
    if key.startswith("model.visual.") or ".vision_tower." in key or key.startswith("model.vision"):
        return "visual", None          # 视觉塔：text-only 后训练可整份丢弃
    if key.startswith("lm_head.") or ".language_model.norm." in key or key == "model.language_model.norm.weight":
        return "head", None            # 训练必需：输出投影 + 最终 norm
    return "other", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="HF 基座目录（含 *.safetensors + *.index.json）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-layers", type=int, default=0, help="只处理前 N 层（调试用，0=全部）")
    a = ap.parse_args()

    shards = sorted(f for f in os.listdir(a.src) if f.endswith(".safetensors"))
    if not shards:
        print(f"[FATAL] {a.src} 下没有 .safetensors")
        sys.exit(1)

    # 1) 扫描：key → (shard, group, layer_idx)
    plan = {}          # group_key -> {"keys": [], "bytes": 0}
    file_of = {}       # key -> shard
    t0 = time.time()
    for sh in shards:
        p = os.path.join(a.src, sh)
        with safe_open(p, framework="pt", device="cpu") as f:
            for k in f.keys():
                group, idx = classify(k)
                if group == "layer" and a.limit_layers and idx >= a.limit_layers:
                    continue
                gk = f"layer_{idx:02d}" if group == "layer" else group
                plan.setdefault(gk, {"keys": [], "bytes": 0})
                plan[gk]["keys"].append(k)
                file_of[k] = sh
    total_bytes = sum(v["bytes"] for v in plan.values())
    n_layers = sum(1 for g in plan if g.startswith("layer_"))
    print(f"[scan] shards={len(shards)} groups={len(plan)} layers={n_layers} keys={len(file_of)}")
    print(f"[scan] 预计输出字节：待精确统计（scan 阶段只读 key 名，{time.time()-t0:.1f}s）")

    if a.dry_run:
        for g in sorted(plan):
            print(f"  {g:12s} keys={len(plan[g]['keys']):4d}  例: {plan[g]['keys'][0]}")
        print("[dry-run] 退出（未落盘）")
        return

    os.makedirs(a.out, exist_ok=True)

    # 2) 逐层落盘：同一组内跨 shard 的张量合并成一个文件
    idx_report = {}
    for g in sorted(plan):
        keys = plan[g]["keys"]
        buf = {}
        written = 0
        for k in keys:
            sh = file_of[k]
            with safe_open(os.path.join(a.src, sh), framework="pt", device="cpu") as f:
                t = f.get_tensor(k)
            buf[k] = t.contiguous()
            written += t.numel() * t.element_size()
        dst = os.path.join(a.out, f"{g}.safetensors")
        save_file(buf, dst)
        h = hashlib.sha256()
        with open(dst, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        idx_report[g] = {"file": os.path.basename(dst), "keys": len(keys),
                         "bytes": written, "sha256_16": h.hexdigest()[:16]}
        print(f"[write] {g:12s} keys={len(keys):4d} {human(written):>9s}  {idx_report[g]['sha256_16']}")
        del buf
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    meta = {"src": os.path.abspath(a.src), "out": os.path.abspath(a.out),
            "n_layers": n_layers, "n_groups": len(idx_report),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "groups": idx_report}
    with open(os.path.join(a.out, "layers_index.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(idx_report)} 个文件 → {a.out}（{time.time()-t0:.1f}s）")


if __name__ == "__main__":
    main()
