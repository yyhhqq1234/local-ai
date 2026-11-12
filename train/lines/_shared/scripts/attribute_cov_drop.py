#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""缺陷归因（第二层）：逐题比对 r3 与 mixv5 的实际回答，找出 cov 掉点的直接机制。

要区分三种可能：
  A 回答变短 ⇒ 覆盖率机械下降（分母感）
  B 回答变长但更泛 ⇒ 具体标识符被稀释
  C 回答风格变成「工具调用 + 理由」模板 ⇒ 该给具体实现时给了工具名
"""
import io
import json
import re
import statistics

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
P2A_R3 = "train/lines/9b-oxcoder/out/eval-2a-r3-v2.json"
P2A_MV = "train/lines/9b-oxcoder/out/eval-2a-mixv5-final.json"

a = json.load(io.open(P2A_R3, encoding="utf-8"))
b = json.load(io.open(P2A_MV, encoding="utf-8"))

print("r3 keys:", [k for k in a.keys()])
det_a = a.get("detail") or a.get("rows") or []
det_b = b.get("detail") or b.get("rows") or []
print("detail n:", len(det_a), len(det_b))
if det_a:
    print("detail sample keys:", list(det_a[0].keys()))

rows = []
n = min(len(det_a), len(det_b))
for i in range(n):
    x, y = det_a[i], det_b[i]
    rx = str(x.get("resp") or x.get("response") or "")
    ry = str(y.get("resp") or y.get("response") or "")
    cx, cy = x.get("cov"), y.get("cov")
    if cx is None:
        cx = x.get("cov_ratio")
    if cy is None:
        cy = y.get("cov_ratio")
    rows.append(dict(id=x.get("id", i), L=x.get("level"), cx=cx, cy=cy,
                     lx=len(rx), ly=len(ry),
                     ix=len(set(IDENT.findall(rx))), iy=len(set(IDENT.findall(ry))),
                     miss_x=x.get("miss") or x.get("missing") or [],
                     miss_y=y.get("miss") or y.get("missing") or []))


def avg(k, arr):
    v = [r[k] for r in arr if isinstance(r.get(k), (int, float))]
    return statistics.mean(v) if v else float("nan")


print("")
print("=" * 88)
print("整体：r3 vs mixv5-final（同 40 题）")
print("=" * 88)
print("  cov      r3 %.3f  →  mixv5 %.3f   (Δ %+.3f)" % (avg("cx", rows), avg("cy", rows), avg("cy", rows) - avg("cx", rows)))
print("  字符数   r3 %.1f  →  mixv5 %.1f   (Δ %+.1f)" % (avg("lx", rows), avg("ly", rows), avg("ly", rows) - avg("lx", rows)))
print("  标识符数 r3 %.1f  →  mixv5 %.1f   (Δ %+.1f)" % (avg("ix", rows), avg("iy", rows), avg("iy", rows) - avg("ix", rows)))
print("  标识符/千字符 r3 %.1f → mixv5 %.1f" % (
    1000 * avg("ix", rows) / max(avg("lx", rows), 1), 1000 * avg("iy", rows) / max(avg("ly", rows), 1)))

gained = [r for r in rows if isinstance(r["cx"], (int, float)) and isinstance(r["cy"], (int, float)) and r["cy"] > r["cx"] + 1e-9]
lost = [r for r in rows if isinstance(r["cx"], (int, float)) and isinstance(r["cy"], (int, float)) and r["cy"] < r["cx"] - 1e-9]
print("  变好 %d 题 / 变差 %d 题 / 持平 %d 题" % (len(gained), len(lost), len(rows) - len(gained) - len(lost)))

print("")
print("变差最大的 6 题：")
for r in sorted(lost, key=lambda x: (x["cy"] - x["cx"]))[:6]:
    print("  %-5s %-3s cov %.2f→%.2f | 字符 %d→%d | 标识符 %d→%d | 缺: %s"
          % (r["id"], r["L"], r["cx"], r["cy"], r["lx"], r["ly"], r["ix"], r["iy"],
             (r["miss_y"] or [])[:4]))

print("")
print("变好最大的 4 题：")
for r in sorted(gained, key=lambda x: -(x["cy"] - x["cx"]))[:4]:
    print("  %-5s %-3s cov %.2f→%.2f | 字符 %d→%d | 标识符 %d→%d"
          % (r["id"], r["L"], r["cx"], r["cy"], r["lx"], r["ly"], r["ix"], r["iy"]))

# 相关性：cov 变化 vs 长度变化
import math
ds = [(r["ly"] - r["lx"], r["cy"] - r["cx"]) for r in rows
      if isinstance(r["cx"], (int, float)) and isinstance(r["cy"], (int, float))]
if len(ds) > 5:
    mx = statistics.mean([d[0] for d in ds])
    my = statistics.mean([d[1] for d in ds])
    num = sum((d[0] - mx) * (d[1] - my) for d in ds)
    den = math.sqrt(sum((d[0] - mx) ** 2 for d in ds) * sum((d[1] - my) ** 2 for d in ds))
    print("")
    print("  相关系数 corr(Δ长度, Δcov) = %.3f" % (num / den if den else 0))
