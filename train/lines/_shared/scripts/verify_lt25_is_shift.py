#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判定 lt25 上升是「整体下移」还是「左尾塌陷」：分块看 p10/p25/p50 与 lt25 的联动。

整体下移（在学）⇒ p50 与 lt25 同步变化，分位间距（p50-p10）基本不变或收窄。
左尾塌陷（记忆化）⇒ p10 掉得比 p50 快，分位间距张开。
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "out", "mix-v5", "train-log.jsonl")


def q(v, p):
    v = sorted(v)
    n = len(v)
    if n < 2:
        return v[0] if v else 0.0
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


rows = [json.loads(l) for l in io.open(LOG, encoding="utf-8") if l.strip() and '"loss"' in l]
print("%-12s %3s %7s %7s %7s %7s %9s %8s" % (
    "块", "n", "p10", "p25", "p50", "p90", "gap50-10", "lt25%"))
i = 0
prev = None
while i < len(rows):
    blk = rows[i:i + 40]
    if len(blk) < 20:
        break
    v = [r["loss"] for r in blk]
    p10, p25, p50, p90 = q(v, .10), q(v, .25), q(v, .50), q(v, .90)
    lt25 = 100.0 * sum(1 for x in v if x < 0.25) / len(v)
    print("%-12s %3d %7.4f %7.4f %7.4f %7.4f %9.4f %8.1f" % (
        "%d-%d" % (blk[0]["step"], blk[-1]["step"]), len(blk), p10, p25, p50, p90, p50 - p10, lt25))
    i += 40

print("")
print("读法：若 lt25 升而 gap(p50-p10) 同时收窄 ⇒ 整体下移（在学，正常）；")
print("      若 lt25 升而 gap 张开 ⇒ 左尾塌陷（记忆化）。")
v = [r["loss"] for r in rows]
print("全程：p10 %.4f  p50 %.4f  gap %.4f  lt25 %.1f%%  (n=%d)" % (
    q(v, .10), q(v, .50), q(v, .50) - q(v, .10),
    100.0 * sum(1 for x in v if x < 0.25) / len(v), len(v)))
