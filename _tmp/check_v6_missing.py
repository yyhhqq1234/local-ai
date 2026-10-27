# -*- coding: utf-8 -*-
"""检查 nsfw-train-v6 中缺失 stype 键的行"""
import os, json, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")

missing = []
with open(os.path.join(DATA, "nsfw-train-v6.jsonl"), "r", encoding="utf-8") as f:
    for ln in f:
        try:
            r = json.loads(ln)
            m = r.get("meta", {})
            if isinstance(m, dict) and "stype" not in m:
                missing.append(r)
        except Exception:
            pass

print(f"missing_stype={len(missing)}")
srcs = collections.Counter(u["meta"].get("__src", "?")[:50] for u in missing)
for k, v in srcs.most_common(10):
    print(f"  {v}x  {k}")

print("\n=== 3 samples ===")
for u in missing[:3]:
    m = u["meta"]
    msgs = u["messages"]
    print(f"  meta_keys={list(m.keys())}")
    print(f"  user[:80]={msgs[0]['content'][:80]!r}")
    print(f"  assistant[:60]={msgs[-1]['content'][:60]!r} ({len(msgs[-1]['content'])} chars)")
    print()
