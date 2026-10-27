# -*- coding: utf-8 -*-
"""对比 nsfw-train-v6 / nsfw-v3 / nsfw(v1) 的行数、meta 分布、样本长度"""
import os, json, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")

def profile(fp, maxscan=20000):
    n = 0
    stypes = collections.Counter()
    lens = []
    first = None
    with open(fp, "r", encoding="utf-8") as f:
        for ln in f:
            n += 1
            if n <= maxscan:
                try:
                    r = json.loads(ln)
                    m = r.get("meta", {})
                    if isinstance(m, dict):
                        stypes[m.get("stype", "?")] += 1
                    msgs = r.get("messages", [])
                    if msgs:
                        lens.append(len(msgs[-1].get("content", "")))
                    if first is None:
                        first = r
                except Exception:
                    pass
    return n, stypes, lens, first

for name in ["nsfw.jsonl", "nsfw-train-v6.jsonl", "nsfw-v3.jsonl"]:
    fp = os.path.join(DATA, name)
    if not os.path.isfile(fp):
        print(f"[MISS] {name}")
        continue
    n, stypes, lens, first = profile(fp)
    lens.sort()
    p50 = lens[len(lens)//2] if lens else 0
    p95 = lens[int(len(lens)*0.95)] if lens else 0
    mx = max(lens) if lens else 0
    print(f"\n{name}: {n} rows, size={os.path.getsize(fp):,}")
    print(f"  stypes={dict(stypes)}")
    print(f"  resp_len p50={p50} p95={p95} max={mx}")
    if first:
        m = first.get("meta", {})
        print(f"  first meta keys={list(m.keys()) if isinstance(m,dict) else m}")
