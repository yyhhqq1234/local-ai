#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_eval_gate.py — P1 门禁（评测侧）：按样本分组判 FAIL，而不是只看聚合指标

## 为什么（mix-v5 缺陷的判据盲区）
mix-v5 的 2A 答卷有 16/40（40%）吐了 `<tool_call>`：
    出 tool_call 的 16 题 Δcov **−0.448**（14 差 / 2 平 / **0 好**）
    没出的 24 题   Δcov **+0.107**
聚合 avg_cov 0.485 把这两群摊平成"整体轻微退化"，掩盖了机制性缺陷。
⇒ 评测必须能分组：**tool_call 率是最便宜的机制指纹**。

## 判据
  ① 2A 评测答卷 `<tool_call>` 率 > 10% ⇒ FAIL（本轮 v5 是 40%）
  ② 答卷里出现盘符绝对路径（`D:\\…`）的比例 > 10% ⇒ WARN（v5 是 37.5%）
  ③ 给出「出/不出 tool_call」两组的 cov 差值，供人工判断机制

## 用法
  python train/lines/_shared/scripts/check_eval_gate.py train/lines/9b-oxcoder/out/eval-2a-mixv5-final.json
  python train/lines/_shared/scripts/check_eval_gate.py --base train/lines/9b-oxcoder/out/eval-2a-r3-v2.json <cand.json>
"""
import argparse
import io
import json
import os
import re
import sys

TCALL = re.compile(r"<tool_call>|<tool_response>")
DRIVE = re.compile(r"[A-Za-z]:\\\\")


def load(p):
    d = json.load(io.open(p, encoding="utf-8"))
    return d, (d.get("detail") or [])


def head(r):
    return str(r.get("resp_head") or r.get("resp") or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cand")
    ap.add_argument("--base", default="", help="基线（同一套题）用于算逐题差")
    ap.add_argument("--max-toolcall-rate", type=float, default=0.10)
    args = ap.parse_args()

    if not os.path.isfile(args.cand):
        sys.exit("[FATAL] 不存在: %s" % args.cand)
    dc, det = load(args.cand)
    n = len(det)
    if not n:
        sys.exit("[FATAL] 无 detail 数据: %s" % args.cand)

    tc = [r for r in det if TCALL.search(head(r))]
    dr = [r for r in det if DRIVE.search(head(r))]
    rate = len(tc) / n
    dr_rate = len(dr) / n

    print("=" * 80)
    print("评测分组门禁 —— %s" % os.path.basename(args.cand))
    print("=" * 80)
    print("  样本 %d · avg_cov %.3f · code_rate %.3f"
          % (n, dc.get("avg_cov", 0), dc.get("code_rate", 0)))
    print("  含 <tool_call>      %2d/%d = %5.1f%%   （红线 %.0f%%）"
          % (len(tc), n, 100 * rate, 100 * args.max_toolcall_rate))
    print("  含盘符绝对路径      %2d/%d = %5.1f%%   （WARN 线 10%%）"
          % (len(dr), n, 100 * dr_rate))

    if args.base and os.path.isfile(args.base):
        db, detb = load(args.base)
        b = {x.get("id"): x for x in detb}
        g1, g0 = [], []
        for r in det:
            k = r.get("id")
            if k not in b:
                continue
            d = (r.get("cov") or 0) - (b[k].get("cov") or 0)
            (g1 if TCALL.search(head(r)) else g0).append(d)
        def rep(v, lab):
            if not v:
                print("  %-18s n=0" % lab)
                return
            lost = sum(1 for x in v if x < -1e-9)
            gain = sum(1 for x in v if x > 1e-9)
            print("  %-18s n=%2d  Δcov 均值 %+.3f  （变差 %d / 变好 %d）"
                  % (lab, len(v), sum(v) / len(v), lost, gain))
        print("  —— 相对基线 %s ——" % os.path.basename(args.base))
        rep(g1, "出 tool_call 的题")
        rep(g0, "不出 tool_call 的题")

    print("")
    bad = []
    if rate > args.max_toolcall_rate:
        bad.append("tool_call 率 %.1f%% > %.0f%%（机制性泄漏，聚合指标不可信）"
                   % (100 * rate, 100 * args.max_toolcall_rate))
    if bad:
        for x in bad:
            print("  [FAIL] %s" % x)
        sys.exit(1)
    if dr_rate > 0.10:
        print("  [WARN] 盘符路径 %.1f%% > 10%% —— 疑似编造路径" % (100 * dr_rate))
    print("  总判定：PASS —— 无机制性工具调用泄漏")


if __name__ == "__main__":
    main()
