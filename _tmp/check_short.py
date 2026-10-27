# -*- coding: utf-8 -*-
"""检查 v3 中过短响应（<50 字）的分布与来源"""
import json, os, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
V3 = os.path.join(BASE, "train", "data", "nsfw-v3.jsonl")

short = []
with open(V3, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        a = r["messages"][-1]["content"]
        if len(a) < 50:
            short.append((r["meta"]["__src"], r["meta"]["win"], len(a), a[:60]))

print(f"short(<50)={len(short)}")
src_cnt = collections.Counter(s[0] for s in short)
for k, v in src_cnt.most_common(10):
    print(f"  {v}x  {k}")
print("\nsamples:")
for s in short[:8]:
    print(f"  win={s[1]} len={s[2]} src={s[0][:50]}")
    print(f"    {s[3]!r}")
