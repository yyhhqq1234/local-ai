#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_shard_index.py —— 为缺 model.safetensors.index.json 的合并目录生成权重索引

transformers 5.x 不再自动扫描 model-*-of-*.safetensors，必须有 index json。
用法：python3 gen_shard_index.py /root/autodl-tmp/kitty-rev/merged-v61
"""
import json
import os
import sys

from safetensors import safe_open


def main():
    d = sys.argv[1]
    shards = sorted(f for f in os.listdir(d) if f.endswith(".safetensors"))
    if not shards:
        raise SystemExit("no shards")
    weight_map = {}
    total = 0
    for s in shards:
        with safe_open(os.path.join(d, s), framework="pt") as f:
            for k in f.keys():
                weight_map[k] = s
                total += 1
    idx = {"metadata": {"total_size": 0}, "weight_map": weight_map}
    out = os.path.join(d, "model.safetensors.index.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
    print(f"[index] {len(shards)} shards, {total} tensors → {out}")


if __name__ == "__main__":
    main()
