#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核读 RE 回归：定位 mixv5 那 1 条「编造」样本，并与 r3 逐题对照。
目的：验收报告里 RE 侧 acc 相同（75.0%）但构成不同（编造 0→1），必须知道是哪道题、编了什么。
"""
import io
import json
import os

P = "train/lines/9b-oxcoder/out/eval-re-regress-mixv5.json"
d = json.load(io.open(P, encoding="utf-8"))
res = {r["label"]: r for r in d["results"]}

labels = [k for k in res]
print("labels:", labels)
for lb, r in res.items():
    print("%-12s hit %2d noarg %2d wrong %2d fake %2d none %2d acc %.3f level %s"
          % (lb, r["hit"], r["noarg"], r["wrong"], r["fake"], r["none"], r["acc"], r.get("level_str")))

det = {lb: res[lb]["detail"] for lb in labels}
base = "r3"
cand = "mixv5-final"

print("")
print("== %s 的 detail 结构 ==" % base)
c0 = det[base][0]
print({k: (v if not isinstance(v, str) or len(v) < 80 else v[:80] + "...") for k, v in c0.items()})

print("")
print("== 逐题对照：状态变化的题 ==")
n = min(len(det[base]), len(det[cand]))
for i in range(n):
    a, b = det[base][i], det[cand][i]
    # 找状态字段
    sa = a.get("status") or a.get("verdict") or a.get("cls")
    sb = b.get("status") or b.get("verdict") or b.get("cls")
    if sa != sb:
        print("")
        print("题 %s (level=%s) r3=%s  mixv5=%s" % (a.get("id", i), a.get("level"), sa, sb))
        print("  ask: %s" % str(a.get("ask"))[:160])
        ea = str(a.get("expect") or a.get("args") or "")[:120]
        eb = str(b.get("expect") or b.get("args") or "")[:120]
        print("  expect: r3=%s | mixv5=%s" % (ea, eb))
        ra = str(a.get("resp") or "")[:300].replace("\n", " ")
        rb = str(b.get("resp") or "")[:300].replace("\n", " ")
        print("  r3 答: %s" % ra)
        print("  mixv5 答: %s" % rb)
