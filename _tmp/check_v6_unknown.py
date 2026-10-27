# -*- coding: utf-8 -*-
"""检查 nsfw-train-v6 中 stype='?' 的 400 行是什么"""
import os, json, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")

unknown = []
with open(os.path.join(DATA, "nsfw-train-v6.jsonl"), "r", encoding="utf-8") as f:
    for ln in f:
        try:
            r = json.loads(ln)
            m = r.get("meta", {})
            if isinstance(m, dict) and m.get("stype") == "?":
                unknown.append(r)
        except Exception:
            pass

print(f"unknown_stype={len(unknown)}")
# 看看来源分布
srcs = collections.Counter(u["meta"].get("__src", "?")[:40] for u in unknown)
for k, v in srcs.most_common(10):
    print(f"  {v}x  {k}")

# 抽 3 条看结构
print("\n=== 3 samples ===")
for u in unknown[:3]:
    m = u["meta"]
    msgs = u["messages"]
    print(f"  src={m.get('__src','?')[:50]} win={m.get('win')}")
    print(f"  user[:80]={msgs[0]['content'][:80]!r}")
    print(f"  assistant[:60]={msgs[-1]['content'][:60]!r} ({len(msgs[-1]['content'])} chars)")
    print()
