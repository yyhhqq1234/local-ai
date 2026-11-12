#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""复核 monitor 的两个决定性数字：分位缺口（记忆化鉴别）+ reserved 阶梯（显存水位）。
只读，不改任何训练状态。"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # train/
LOG = os.path.join(ROOT, "out", "mix-v5", "train-log.jsonl")
MEM = os.path.join(ROOT, "out", "mix-v5", "mem-trace.jsonl")


def q(v, p):
    v = sorted(v)
    i = (len(v) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


rows = [json.loads(l) for l in io.open(LOG, encoding="utf-8") if l.strip() and '"loss"' in l]
last = rows[-1]["step"]
first = [r["loss"] for r in rows if r["step"] <= 200]
tail = [r["loss"] for r in rows if r["step"] > last - 200]

print("[A] 分位缺口复核  last_step=%d  n_first=%d n_tail=%d" % (last, len(first), len(tail)))
print("     %-6s %10s %10s %10s" % ("分位", "前200步", "近200步", "delta"))
for p in (0.01, 0.05, 0.10, 0.25, 0.50):
    a, b = q(first, p), q(tail, p)
    print("     p%-5.0f %10.4f %10.4f %+10.4f" % (p * 100, a, b, b - a))
gap_f = q(first, .5) - q(first, .01)
gap_t = q(tail, .5) - q(tail, .01)
gap5_f = q(first, .5) - q(first, .05)
gap5_t = q(tail, .5) - q(tail, .05)
print("     gap(p50-p1)  %.4f -> %.4f   收窄 %.1f%%" % (gap_f, gap_t, 100 * (gap_f - gap_t) / gap_f))
print("     gap(p50-p5)  %.4f -> %.4f   收窄 %.1f%%" % (gap5_f, gap5_t, 100 * (gap5_f - gap5_t) / gap5_f))

mem = [json.loads(x) for x in io.open(MEM, encoding="utf-8") if x.strip()]
print("")
print("[B] mem-trace 复核  rows=%d  keys=%s" % (len(mem), sorted(mem[0].keys())))
prev = None
chg = 0
for r in mem:
    key = round(r.get("reserved_gib", 0), 3)
    if prev is None or abs(key - prev) > 0.001:
        print("     step %-6s reserved %.3f  peak %.3f  free %.3f" % (
            r.get("step"), r.get("reserved_gib", 0), r.get("peak_gib", 0), r.get("free_gib", 0)))
        chg += 1
    prev = key
print("     变化点 %d 个 / 共 %d 行；末行 step=%s reserved=%.3f" % (
    chg, len(mem), mem[-1].get("step"), mem[-1].get("reserved_gib", 0)))
last_chg = None
for i, r in enumerate(mem):
    if i == 0 or abs(round(r.get("reserved_gib", 0), 3) - round(mem[i - 1].get("reserved_gib", 0), 3)) > 0.001:
        last_chg = (i, r.get("step"))
print("     最后一次抬升：行%d / step %s → 之后 %d 步零增量" % (
    last_chg[0], last_chg[1], len(mem) - 1 - last_chg[0]))
