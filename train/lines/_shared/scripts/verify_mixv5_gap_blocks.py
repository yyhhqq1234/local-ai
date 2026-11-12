#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""非重叠窗口复核 gap(p50-p5) —— 判定 monitor 的"抖动而非趋势"是否成立。
滑动窗（近 200 步）相邻窗口共享 39/40 样本，会把噪声平滑成假单调；
非重叠窗口每次换掉全部样本，才看得出真实波动幅度。"""
import io
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # train/
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
last = rows[-1]["step"]
print("last_step = %d   记录点 = %d   (logging_steps=5 ⇒ 每 200 步 = 40 点)" % (last, len(rows)))

print("")
print("== 非重叠 200 步窗口 ==")
print("  %-12s %3s %8s %8s %9s %9s" % ("窗口", "n", "gap50-5", "gap50-10", "min/mean", "min"))
gaps = []
i = 0
while i < len(rows):
    blk = rows[i:i + 40]
    if len(blk) < 20:
        break
    ls = [r["loss"] for r in blk]
    g5 = q(ls, .5) - q(ls, .05)
    g10 = q(ls, .5) - q(ls, .10)
    mn = min(ls)
    mean = sum(ls) / len(ls)
    gaps.append(g5)
    print("  %-12s %3d %8.4f %8.4f %9.4f %9.4f"
          % ("%d-%d" % (blk[0]["step"], blk[-1]["step"]), len(blk), g5, g10, mn / mean, mn))
    i += 40

print("")
print("== 抖动统计（非重叠窗口）==")
print("  gap50-5: n=%d  min %.4f  max %.4f  极差 %.4f  sd %.4f"
      % (len(gaps), min(gaps), max(gaps), max(gaps) - min(gaps), statistics.pstdev(gaps)))
print("  ⇒ 抖动带 ±%.4f，占黄线 0.28 的 %.0f%%" % (
    (max(gaps) - min(gaps)) / 2, 100 * ((max(gaps) - min(gaps)) / 2) / 0.28))

all_loss = [r["loss"] for r in rows]
tail = [r["loss"] for r in rows if r["step"] > last - 200]
print("")
print("== min/mean 双口径 ==")
print("  全量      min/mean = %.4f  (n=%d, min=%.4f)" % (
    min(all_loss) / (sum(all_loss) / len(all_loss)), len(all_loss), min(all_loss)))
print("  近200步   min/mean = %.4f  (n=%d, min=%.4f)" % (
    min(tail) / (sum(tail) / len(tail)), len(tail), min(tail)))
lo = min(rows, key=lambda r: r["loss"])
print("  全量最低点: step %s loss %.4f  ← 孤立点若在此处，全局口径会被它永久压住"
      % (lo["step"], lo["loss"]))
