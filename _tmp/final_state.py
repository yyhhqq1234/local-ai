# -*- coding: utf-8 -*-
"""最终状态确认：训练链路 + 产物清单"""
import os

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")

print("=== 训练链路 ===")
print("  数据源: build_nsfw_sft_v3.py → nsfw.jsonl (13,668 rows)")
print("  组装:   build_final.py → final-nsfw/joint/re")
print("  混合:   build_mix.py → mix-nsfw/joint (meta 透传)")
print("  训练:   train_qlora9b.py --data mix-nsfw.jsonl")

print("\n=== 当前 NSFW 产物 ===")
for name in sorted(os.listdir(DATA)):
    if not name.endswith(".jsonl"):
        continue
    if "nsfw" in name.lower() or name in ("mix-nsfw.jsonl", "mix-joint.jsonl"):
        fp = os.path.join(DATA, name)
        n = sum(1 for _ in open(fp, "rb"))
        size = os.path.getsize(fp)
        print(f"  {name:28s} {n:>8,} rows  {size:>12,} bytes")

print("\n=== 已删除（防重复训练）===")
print("  数据: nsfw-train-v2/v3/v4/v5/v6.jsonl")
print("  脚本: nsfw_final_merge.py / nsfw_final_merge_v4.py /")
print("        nsfw_lexicon_expand.py / nsfw_train_merge.py")
print("\n[DONE]")
