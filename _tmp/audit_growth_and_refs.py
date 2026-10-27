# -*- coding: utf-8 -*-
"""审计：build_final 行数增长来源 + 全 scripts 引用已删除文件"""
import os, re

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
SCRIPTS = os.path.join(TRAIN, "scripts")

# 1) 读 build_final.py，找它如何从 nsfw.jsonl 生成 final-nsfw
bf = open(os.path.join(SCRIPTS, "build_final.py"), "r", encoding="utf-8").read()
print("=== build_final.py 关键片段 ===")
# 找 nsfw 相关行
for i, line in enumerate(bf.split("\n")):
    if any(k in line.lower() for k in ["nsfw", "final", "row", "append", "extend", "write", "iter"]):
        print(f"{i:4}: {line}")
