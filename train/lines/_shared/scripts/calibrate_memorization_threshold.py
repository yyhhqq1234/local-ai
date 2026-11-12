#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用已验收基线校准记忆化阈值：r3（RE 75.0%，判为合格）自己的 loss 分布长什么样。

为什么必须这么做：
  min/mean<0.30、lt25 份额、cv 这些阈值是从"单一域、单一分布"的直觉定的。
  但 mix-v5 是双峰数据（92% 短 kitty + 8% 长长编程），kitty 段在 r3 阶段已被拟合到低 loss，
  2A 段从高 loss 往下走 —— 混合分布天然拉大 min/mean、天然抬高 lt25 份额。
  若 r3 自己终点的 min/mean 也是 0.2 量级，那本次 0.2375 就不是"记忆化"，是"这个数据集的正常形态"。
"""
import io
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # train/
RUNS = [
    ("r3 (已验收 RE 75.0%)", os.path.join(ROOT, "out", "re-stage1-r3", "train-log.jsonl")),
    ("2a (已判废)", os.path.join(ROOT, "out", "2a-stage", "train-log.jsonl")),
    ("mix-v5 (本轮)", os.path.join(ROOT, "out", "mix-v5", "train-log.jsonl")),
]


def q(v, p):
    v = sorted(v)
    n = len(v)
    if n < 2:
        return v[0] if v else 0.0
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def stats(ls):
    mean = sum(ls) / len(ls)
    mn = min(ls)
    return dict(
        n=len(ls), mean=mean, min=mn,
        ratio=mn / mean if mean else 0,
        lt25=100.0 * sum(1 for x in ls if x < 0.25) / len(ls),
        lt15=100.0 * sum(1 for x in ls if x < 0.15) / len(ls),
        lt10=100.0 * sum(1 for x in ls if x < 0.10) / len(ls),
        cv=statistics.pstdev(ls) / mean if mean else 0,
        gap=q(ls, .5) - q(ls, .05),
    )


print("=" * 96)
print("%-24s %6s %7s %7s %8s %8s %8s %7s %7s" % (
    "run/块", "n", "mean", "min", "min/mean", "lt25%", "lt15%", "cv", "gap50-5"))
print("=" * 96)

for label, path in RUNS:
    if not os.path.isfile(path):
        print("%-24s [缺] %s" % (label, path))
        continue
    rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip() and '"loss"' in l]
    allv = [r["loss"] for r in rows]
    s = stats(allv)
    print("%-24s %6d %7.4f %7.4f %8.4f %8.1f %8.1f %7.3f %7.4f  ← 全程" % (
        label, s["n"], s["mean"], s["min"], s["ratio"], s["lt25"], s["lt15"], s["cv"], s["gap"]))
    # 末四分之一（与 mix-v5 当前进度可比的位置）
    tailn = max(40, len(rows) // 4)
    st = stats([r["loss"] for r in rows[-tailn:]])
    print("%-24s %6d %7.4f %7.4f %8.4f %8.1f %8.1f %7.3f %7.4f  ← 末 %d 点（可比位置）" % (
        "", st["n"], st["mean"], st["min"], st["ratio"], st["lt25"], st["lt15"], st["cv"], st["gap"], tailn))
    print("-" * 96)

# mix-v5 逐块（step 200 对齐），重点看最近三块
print("")
print("mix-v5 逐块（非重叠 200 步）")
print("%-12s %4s %7s %7s %8s %8s %8s %7s %7s" % (
    "块", "n", "mean", "min", "min/mean", "lt25%", "lt15%", "cv", "gap50-5"))
rows = [json.loads(l) for l in io.open(RUNS[2][1], encoding="utf-8") if l.strip() and '"loss"' in l]
i = 0
while i < len(rows):
    blk = rows[i:i + 40]
    if len(blk) < 20:
        break
    s = stats([r["loss"] for r in blk])
    print("%-12s %4d %7.4f %7.4f %8.4f %8.1f %8.1f %7.3f %7.4f" % (
        "%d-%d" % (blk[0]["step"], blk[-1]["step"]), s["n"], s["mean"], s["min"],
        s["ratio"], s["lt25"], s["lt15"], s["cv"], s["gap"]))
    i += 40

# 单点敏感性：最近 400 点剔掉 k 个最低
tail = [r["loss"] for r in rows if r["step"] > rows[-1]["step"] - 400]
print("")
print("单点敏感性（近 400 点，挨个剔最低 k 个）")
for k in (0, 1, 2, 3, 5, 10):
    t = sorted(tail)[k:]
    s = stats(t)
    print("  剔 %-2d 个: min %.4f mean %.4f min/mean %.4f lt25 %.1f%%"
          % (k, s["min"], s["mean"], s["ratio"], s["lt25"]))
