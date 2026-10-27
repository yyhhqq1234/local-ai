# -*- coding: utf-8 -*-
"""最终审计：已删除文件引用 + 训练入口读取确认"""
import os, re

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
SCRIPTS = os.path.join(TRAIN, "scripts")
DATA = os.path.join(TRAIN, "data")

DEAD = ["nsfw-train-v2", "nsfw-train-v3", "nsfw-train-v4", "nsfw-train-v5", "nsfw-train-v6"]

print("=== scripts 引用已删除文件 ===")
found_any = False
for fn in sorted(os.listdir(SCRIPTS)):
    if not fn.endswith(".py"):
        continue
    fp = os.path.join(SCRIPTS, fn)
    txt = open(fp, "r", encoding="utf-8", errors="ignore").read()
    hits = [d for d in DEAD if d in txt]
    if hits:
        found_any = True
        print(f"  {fn}: {hits}")
if not found_any:
    print("  无引用 — 安全")

print("\n=== train_qlora9b.py 数据入口 ===")
fp = os.path.join(SCRIPTS, "train_qlora9b.py")
txt = open(fp, "r", encoding="utf-8", errors="ignore").read()
refs = re.findall(r"[A-Za-z0-9_\-\.]*\.jsonl", txt)
uniq = []
for r in refs:
    if r not in uniq:
        uniq.append(r)
print(f"  jsonl refs: {uniq}")

print("\n=== 最终 data/ NSFW 相关产物 ===")
for name in sorted(os.listdir(DATA)):
    if name.endswith(".jsonl") and ("nsfw" in name.lower() or name == "nsfw.jsonl"):
        n = sum(1 for _ in open(os.path.join(DATA, name), "rb"))
        size = os.path.getsize(os.path.join(DATA, name))
        print(f"  {name:28s} {n:>8,} rows  {size:>12,} bytes")
