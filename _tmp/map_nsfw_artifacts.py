# -*- coding: utf-8 -*-
"""盘点 train/data/ 下所有 NSFW 相关产物：行数/首条结构/mtime，判定最新与旧版"""
import os, json, glob, time

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")

def first_record(fp):
    """读首行，返回 (msg_keys, meta_keys) 概览"""
    try:
        with open(fp, "r", encoding="utf-8") as f:
            ln = f.readline()
        r = json.loads(ln)
        keys = list(r.keys())
        meta = r.get("meta", {})
        return keys, list(meta.keys()) if isinstance(meta, dict) else []
    except Exception as e:
        return None, str(e)

def line_count(fp):
    n = 0
    with open(fp, "rb") as f:
        for _ in f:
            n += 1
    return n

targets = []
for fn in sorted(os.listdir(DATA)):
    fp = os.path.join(DATA, fn)
    if os.path.isfile(fp) and fn.endswith(".jsonl"):
        targets.append((fn, fp))

print(f"{'file':<34} {'lines':>8} {'size':>12} {'mtime':<12} first_keys / meta")
print("-" * 100)
for fn, fp in targets:
    sz = os.path.getsize(fp)
    mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
    keys, meta = first_record(fp)
    # 只统计小文件的行数（>50MB 太慢就跳过精确计数）
    if sz < 20_000_000:
        lc = line_count(fp)
    else:
        lc = -1
    lc_s = str(lc) if lc >= 0 else "big"
    print(f"{fn:<34} {lc_s:>8} {sz:>12,} {mt:<12} {keys} / {meta}")

print("\n=== final-manifest.json ===")
mf = os.path.join(DATA, "final-manifest.json")
if os.path.isfile(mf):
    print(open(mf, "r", encoding="utf-8").read())
