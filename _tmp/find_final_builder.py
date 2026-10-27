# -*- coding: utf-8 -*-
"""在 scripts/ 中查找产出 final-joint / final-nsfw 的脚本，并提取其输入文件名"""
import os, re, glob

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
SCRIPTS = os.path.join(BASE, "train", "scripts")

# 关键词：产出 final 或读取 nsfw 的脚本
KEYS = ["final", "joint", "nsfw", "mix", "build"]

def scan(fp):
    txt = open(fp, "r", encoding="utf-8", errors="ignore").read()
    # 找 .jsonl 引用
    refs = re.findall(r"[A-Za-z0-9_\-\.]*\.jsonl", txt)
    return txt, refs

hits = []
for fn in sorted(os.listdir(SCRIPTS)):
    fp = os.path.join(SCRIPTS, fn)
    if not os.path.isfile(fp):
        continue
    if not fn.endswith(".py"):
        continue
    txt, refs = scan(fp)
    has_out = ("final-joint" in txt) or ("final-nsfw" in txt) or ("final_joint" in txt)
    has_in = ("nsfw" in txt) and ("jsonl" in txt)
    if has_out or has_in:
        hits.append((fn, refs))

print("=== scripts referencing final/nsfw jsonl ===")
for fn, refs in hits:
    uniq = []
    for r in refs:
        if r not in uniq:
            uniq.append(r)
    print(f"\n{fn}:")
    for r in uniq:
        print(f"    {r}")
