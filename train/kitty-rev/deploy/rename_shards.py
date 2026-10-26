#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rename_shards.py —— A 方案：把 safetensors 里 model.language_model.* 真改名为 model.*

B 方案（只改 index.json）已实测失败：
  ValueError: missing source tensor 'model.layers.0.linear_attn.in_proj_qkv.weight'
  原因：转换器按 index 定位文件后，用键名在文件内部查找张量 → 文件内仍是旧名 → 查不到。
所以必须重写 shard 内容（逐 tensor 读→改名→写），bf16 51G，IO 约 10-15 min。

做法：逐 shard 处理（单 shard ~4.3G 内存），写到新目录，最后补 index/config/tokenizer。
"""
import json
import os
import shutil
import sys
import time

from safetensors import safe_open
from safetensors.torch import save_file

SRC = "/root/autodl-tmp/kitty-rev/merged/Qwen3.8-27B-kittyrev"
DST = "/root/autodl-tmp/kitty-rev/merged-text2/Qwen3.8-27B-kittyrev"
PREFIX_OLD = "model.language_model."
PREFIX_NEW = "model."
COPY = (".json", ".jinja", ".model", ".txt")


def main():
    os.makedirs(DST, exist_ok=True)
    shards = sorted(f for f in os.listdir(SRC) if f.endswith(".safetensors"))
    print(f"[plan] {len(shards)} shards → {DST}", flush=True)

    new_map = {}
    t0 = time.time()
    for i, name in enumerate(shards, 1):
        src = os.path.join(SRC, name)
        out = os.path.join(DST, name)
        tensors, meta = {}, {}
        with safe_open(src, framework="pt", device="cpu") as f:
            for k in f.keys():
                nk = k.replace(PREFIX_OLD, PREFIX_NEW, 1) if k.startswith(PREFIX_OLD) else k
                tensors[nk] = f.get_tensor(k)
                new_map[nk] = name
                try:
                    meta[nk] = f.get_slice(k).get_shape()
                except Exception:
                    pass
        save_file(tensors, out, metadata={"format": "pt"})
        del tensors
        print(f"[{i}/{len(shards)}] {name}  {time.time()-t0:.0f}s  keys={len(meta)}", flush=True)

    json.dump({"metadata": {"total_size": 0}, "weight_map": new_map},
              open(os.path.join(DST, "model.safetensors.index.json"), "w"),
              ensure_ascii=False, indent=2)

    cfg = json.load(open(os.path.join(SRC, "config.json")))
    tc = cfg.get("text_config") or {}
    for k in ("vision_config", "image_token_id", "video_token_id",
              "vision_start_token_id", "vision_end_token_id", "language_model_only",
              "text_config"):
        cfg.pop(k, None)
    for k, v in tc.items():
        if k in ("architectures", "model_type"):
            continue
        cfg.setdefault(k, v)
    cfg["architectures"] = ["Qwen3_5ForCausalLM"]
    cfg["model_type"] = "qwen3_5_text"
    json.dump(cfg, open(os.path.join(DST, "config.json"), "w"), ensure_ascii=False, indent=2)

    for name in os.listdir(SRC):
        if name.endswith(COPY) and name != "config.json":
            s, d = os.path.join(SRC, name), os.path.join(DST, name)
            if not os.path.exists(d):
                shutil.copy2(s, d)

    print(f"[done] keys={len(new_map)}  {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
