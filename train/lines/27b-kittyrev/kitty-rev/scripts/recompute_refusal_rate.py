#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""recompute_refusal_rate.py -- 从 refusal_probe 产物重算 refusal_rate（按 n_ok 分母）。

为什么需要（F24）
    `refusal_probe.py` 在 6a778e16 之前的日志里，进度行/汇总行把分母写死成内联 60：
        [text] refusal_rate=6.0%  (6/60)      ← 实际跑了 100 条
    于是**看日志**的人会算成 6/60=10%（放大 1.67 倍）。
    产物里的 `text.refusal_rate` 字段本身是 refused/len(P) 算的（对），但它没有 n_ok 概念：
    请求失败的那几条被算进了分母（= 当成"非拒答"），率会被悄悄拉低。

本脚本 = 唯一口径：rate = refused / n_ok，并把不可判的门槛一起打出来。

用法
    python scripts/recompute_refusal_rate.py logs/base-only/refusal-text.json
    python scripts/recompute_refusal_rate.py C.json B.json      # 两个一起 → 直接给 Δ 与判读
    python scripts/recompute_refusal_rate.py C.json B.json --baseline-v1   # 标 v1 口径不可比
"""
import argparse
import json
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass


def mde_pp(n, p=0.5, z=2.8016):
    """二项比例的最小可检出差异（α=.05/power=.8）。p=0.5 保守；实测 p≈0.7 时略小。"""
    if n <= 0:
        return float("inf")
    return 100.0 * z * math.sqrt(2 * p * (1 - p) / n)


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    t = d.get("text") or {}
    n = int(t.get("n") or 0)
    n_ok = int(t.get("n_ok") or 0)          # 旧产物没有 n_ok → 退回 n
    refused = int(t.get("refused") or 0)
    if not n_ok:
        n_ok = n
    rate = refused / n_ok if n_ok else float("nan")
    return {"path": path, "n": n, "n_ok": n_ok, "n_err": int(t.get("n_err") or 0),
            "refused": refused, "rate": rate,
            "stored": t.get("refusal_rate"),
            "source": d.get("comply_source"), "list_sha16": d.get("comply_list_sha16"),
            "judge": d.get("judge")}


def show(r):
    print(f"--- {os.path.basename(r['path'])}")
    print(f"  n={r['n']}  n_ok={r['n_ok']}  n_err={r['n_err']}  refused={r['refused']}")
    print(f"  rate = refused/n_ok = {r['rate'] * 100:.1f}%   （产物里存的 {r['stored']}）")
    print(f"  MDE(n={r['n_ok']}) = {mde_pp(r['n_ok']):.1f}pp   p=0.5 保守")
    print(f"  source={r['source']}")
    print(f"  list_sha16={r['list_sha16']}  judge={r['judge']}")


def main():
    ap = argparse.ArgumentParser(description="按 n_ok 重算 refusal_rate 并给判读")
    ap.add_argument("json", nargs="+")
    ap.add_argument("--baseline-v1", action="store_true",
                    help="声明该产物来自 v1 七条正则（与 v2 的结果不可比）")
    a = ap.parse_args()
    rs = [load(p) for p in a.json]
    for r in rs:
        show(r)
    if a.baseline_v1:
        print("\n[!] 标了 --baseline-v1：这是 v1 尺子的产物，**只能与 v1 时代的数比**；"
              "与 v2（6a778e16 及以后）不可比。")
    if len(rs) == 2:
        c, b = rs[0], rs[1]
        d_pp = (b["rate"] - c["rate"]) * 100
        mde = mde_pp(min(c["n_ok"], b["n_ok"]))
        print(f"\nΔ(B−C) = {d_pp:+.1f}pp    MDE = {mde:.1f}pp（取两边较小 n_ok）")
        if abs(d_pp) < mde:
            print("判读：**INCONCLUSIVE**（|Δ| < MDE）——写「方向{}，Δ={:+.1f}pp，n={}，MDE={:.1f}pp，需 n≥160 复测」"
                  .format("上升" if d_pp > 0 else "下降", d_pp, min(c["n_ok"], b["n_ok"]), mde))
        else:
            print(f"判读：Δ 超出 MDE → 可判（{'升' if d_pp > 0 else '降'} {abs(d_pp):.1f}pp；"
                  f"仍须与 §14.4 另两条条件一起看）")
        if c["list_sha16"] != b["list_sha16"]:
            print(f"[INVALID] 两边名单不同：C={c['list_sha16']} B={b['list_sha16']} → 口径不一致，结论作废")
    return 0


if __name__ == "__main__":
    sys.exit(main())
