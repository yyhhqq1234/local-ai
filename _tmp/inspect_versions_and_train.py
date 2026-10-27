# -*- coding: utf-8 -*-
"""检查 versions/ 目录 + train_qlora9b.py 读取的数据文件"""
import os, re

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")
SCRIPTS = os.path.join(BASE, "train", "scripts")

print("=== train/data/versions/ ===")
ver = os.path.join(DATA, "versions")
if os.path.isdir(ver):
    for root, dirs, files in os.walk(ver):
        for fn in files:
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, ver)
            print(f"  {os.path.getsize(fp):>12,}  {rel}")
else:
    print("  [MISS]")

print("\n=== train_qlora9b.py data refs ===")
fp = os.path.join(SCRIPTS, "train_qlora9b.py")
txt = open(fp, "r", encoding="utf-8", errors="ignore").read()
refs = re.findall(r"[A-Za-z0-9_\-\.]*\.jsonl", txt)
uniq = []
for r in refs:
    if r not in uniq:
        uniq.append(r)
print("  jsonl refs:", uniq)
# 找数据路径上下文
for ln in txt.splitlines():
    if ".jsonl" in ln or "nsfw" in ln.lower() or "mix" in ln.lower():
        print(f"    {ln.strip()}")
