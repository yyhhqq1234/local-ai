#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""flatten_keys.py —— 把 merged 的 `model.language_model.*` 键名剥成 `model.*`

背景（2026-10-22）：
  tools.convert --recipe qwen3_8_27b 期望 `model.layers.N.*`，
  而 merged（Qwen3_5ForConditionalGeneration）的键是 `model.language_model.layers.N.*`
  → ValueError: missing source tensor 'model.layers.0.linear_attn.in_proj_qkv.weight'

做法：逐 shard 读 → 改键 → 写新 shard + 新 index.json + 复制 config/tokenizer。
  safetensors 的键名在文件内，不能只改 index，必须重写。

用法：
  python flatten_keys.py --src merged/Qwen3.8-27B-kittyrev --dst merged-flat [--dry-run]
"""
import argparse
import json
import os
import shutil

from safetensors.torch import load_file, save_file

PREFIX = "model.language_model."
TARGET = "model."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-shard-bytes", type=int, default=5 * 1024 ** 3)
    a = ap.parse_args()

    idx_path = os.path.join(a.src, "model.safetensors.index.json")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)

    wmap = idx["weight_map"]
    renamed = {}
    hit = miss = 0
    for k, shard in wmap.items():
        if k.startswith(PREFIX):
            renamed[k[len(PREFIX):] if False else TARGET + k[len(PREFIX):]] = shard
            hit += 1
        else:
            renamed[k] = shard
            miss += 1
    print(f"[keys] total={len(wmap)} prefixed={hit} untouched={miss}")
    sample = [k for k in renamed if k.startswith("model.layers.0.")][:4]
    print(f"[keys] 样例(改后): {sample}")

    if a.dry_run:
        print("[dry-run] 不写盘")
        return

    os.makedirs(a.dst, exist_ok=True)

    # 按 src 的 shard 分组处理（一趟遍历，old→new 直接配对）
    by_shard = {}
    for old_k, shard in wmap.items():
        new_k = (TARGET + old_k[len(PREFIX):]) if old_k.startswith(PREFIX) else old_k
        by_shard.setdefault(shard, []).append((old_k, new_k))

    new_wmap = {}
    for i, (shard, pairs) in enumerate(sorted(by_shard.items())):
        src_p = os.path.join(a.src, shard)
        out_name = f"model-{i+1:05d}.safetensors"
        sd = load_file(src_p)
        out = {}
        for old_k, new_k in pairs:
            if old_k is None:
                continue
            out[new_k] = sd[old_k]
        save_file(out, os.path.join(a.dst, out_name), metadata={"format": "pt"})
        for _, new_k in pairs:
            new_wmap[new_k] = out_name
        print(f"[shard] {shard} -> {out_name}  tensors={len(out)}")

    idx_out = {"metadata": idx.get("metadata", {}), "weight_map": new_wmap}
    with open(os.path.join(a.dst, "model.safetensors.index.json"), "w", encoding="utf-8") as f:
        json.dump(idx_out, f, indent=2)
    print(f"[done] index 写出 weight_map={len(new_wmap)}")

    # 复制非权重文件（config / tokenizer / generation_config）
    copied = 0
    for fn in os.listdir(a.src):
        if fn.endswith(".safetensors") or fn == "model.safetensors.index.json":
            continue
        p = os.path.join(a.src, fn)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(a.dst, fn))
            copied += 1
    print(f"[done] 复制附属文件 {copied} 个")


if __name__ == "__main__":
    main()
