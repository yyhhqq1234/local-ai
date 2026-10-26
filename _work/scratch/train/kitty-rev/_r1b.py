# -*- coding: utf-8 -*-
"""从 log 提取第 1 轮（修好 53 工具 description 的新 schema 口径）的分类结果"""
import re
from collections import Counter
lines = open("logs/v6/base-all23-fixed.log", encoding="utf-8", errors="replace").read().splitlines()
r1 = []
inr1 = False
for L in lines:
    if "===== 第 1/3 轮" in L: inr1 = True; continue
    if "===== 第 2/3 轮" in L: inr1 = False
    if inr1:
        m = re.match(r"\[(\d+)/23\]\s+(\S+)\s+(PASS|FAIL)\s+(.*)", L)
        if m:
            r1.append((int(m.group(1)), m.group(2), m.group(3), m.group(4).strip()))
print(f"第1轮完成 {len(r1)}/23")
c = Counter()
for i, cat, res, why in r1:
    c[(cat, res)] += 0
cats = {}
for i, cat, res, why in r1:
    cats.setdefault(cat, [0, 0])
    cats[cat][1] += 1
    if res == "PASS": cats[cat][0] += 1
tot_ok = sum(1 for x in r1 if x[2] == "PASS")
print(f"\n第1轮总: {tot_ok}/{len(r1)} = {tot_ok/max(1,len(r1))*100:.1f}%")
for k, (ok, t) in sorted(cats.items(), key=lambda x: -x[1][1]):
    print(f"  {k:<22} {ok}/{t}")
fails = [(i, cat, why) for i, cat, res, why in r1 if res == "FAIL"]
print(f"\nFAIL {len(fails)} 题:")
for i, cat, why in fails:
    print(f"  题{i:>2} [{cat:<18}] {why[:80]}")
