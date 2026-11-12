#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""2B 门控训练集内容剖析（只读）"""
import json, re, sys, collections, os

P = r"train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl"
rows = []
with open(P, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

print("TOTAL", len(rows))

# id 后缀分类
suf = collections.Counter()
for r in rows:
    i = r.get("id", "")
    suf[i.rsplit("#", 1)[-1] if "#" in i else "(none)"] += 1
print("ID_SUFFIX", dict(suf))

# system 提示分布
sysc = collections.Counter()
for r in rows:
    m = r.get("messages", [])
    if m and m[0].get("role") == "system":
        sysc[m[0]["content"][:60]] += 1
    else:
        sysc["(NO_SYSTEM)"] += 1
print("\n=== SYSTEM TOP10 ===")
for k, v in sysc.most_common(10):
    print(f"  {v:6d}  {k!r}")

# 每条消息数分布
nmsg = collections.Counter(len(r.get("messages", [])) for r in rows)
print("\nMSG_COUNT", dict(nmsg))

# 长度分布（字符）
def asst(r):
    for m in r.get("messages", []):
        if m.get("role") == "assistant":
            return m.get("content", "")
    return ""

lens = [len(asst(r)) for r in rows]
lens.sort()
n = len(lens)
print("\n=== ASSISTANT 字符长度分位 ===")
for q in (0, 10, 25, 50, 75, 90, 95, 99, 100):
    print(f"  p{q:<3d} = {lens[min(n-1, int(n*q/100))]}")

# 空 assistant
empty = sum(1 for x in lens if x == 0)
print("EMPTY_ASSISTANT", empty)

# 按 id 后缀看 assistant 长度中位数
print("\n=== 后缀 x assistant 中位长度 ===")
by = collections.defaultdict(list)
for r in rows:
    i = r.get("id", "")
    s = i.rsplit("#", 1)[-1] if "#" in i else "(none)"
    by[s].append(len(asst(r)))
for s, v in sorted(by.items(), key=lambda x: -len(x[1])):
    v.sort()
    print(f"  {s:<8} n={len(v):6d}  median={v[len(v)//2]:6d}  max={v[-1]:7d}")

# 样本示例：每类取 1 条
print("\n=== 示例（每后缀一条，assistant 前 220 字）===")
seen = set()
for r in rows:
    i = r.get("id", "")
    s = i.rsplit("#", 1)[-1] if "#" in i else "(none)"
    if s in seen:
        continue
    seen.add(s)
    msgs = r.get("messages", [])
    print(f"\n--- [{s}] id={i}")
    for m in msgs:
        c = (m.get("content") or "").replace("\n", "\\n")
        print(f"  {m['role']:>9}: {c[:220]}")
