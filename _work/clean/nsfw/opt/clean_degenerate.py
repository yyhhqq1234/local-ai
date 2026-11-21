# -*- coding: utf-8 -*-
"""clean_degenerate.py — 退化样本清洗（只动 permit 行，regular 原样透传）。

判据（全部作用在 assistant 正文上）
-----------------------------------
  HEART_RUN             心形字符（❤♥♡ 等）连续 ≥3           → 弃
  TILDE_RUN             波浪号（～ ~ 〜）连续 ≥3             → 弃
  INTERJ_RUN            语气/拟声词（啊嗯哦哈呀呜…）连续 ≥5   → 弃
  CHAR_RUN8             任意非标点字符连续 ≥8                → 弃
  SINGLE_CHAR_DOMINANT  单一字符占非空白正文比 > 0.35         → 弃
  REPEAT_5GRAM          去标点后同一 5-gram 出现 ≥8 次        → 弃
  LEN_SHORT / LEN_LONG  正文 < 200 字 / > 6000 字             → 弃

为什么不是「任意字符连续 3 个就弃」
----------------------------------
实测 permit 集里 3 连字符绝大多数是正常成人向描写（「啊啊啊」「啪啪啪」「……」），
一刀切会误杀 ~1200 行（占 permit 21%）。因此运行口径按字符类别收紧：
刷屏类（心形/波浪）3 连即弃；语气词 5 连、其它字符 8 连。
需要操作者原始口径时加 `--strict-literal`（任意字符 ≥3 连续即弃，含标点）。

输出
----
  cleaned/opt/nsfw-clean-v2.jsonl    清洗后全集（原顺序；permit 洗掉退化的 + regular 全留）
  cleaned/opt/drops-degenerate.jsonl 剔除清单（行号/哈希/长度/原因码/指标，**不含原文**）
  _work/clean/nsfw/opt/clean-stats.json

用法
----
  python _work/clean/nsfw/opt/clean_degenerate.py [--strict-literal] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opt_common as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict-literal", action="store_true",
                    help="原始口径：任意字符连续 ≥3 即弃（含标点/语气词）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = C.load_rows()
    print("[in] rows=%d" % len(rows))

    keep, drops = [], []
    code_cnt = Counter()
    branch_cnt = Counter()
    literal_would_drop = 0
    minor_dropped = 0

    for lineno, row in enumerate(rows, 1):
        branch = C.common.branch_of(row)
        branch_cnt[branch] += 1
        body = C.assistant_of(row)

        # 仅清洗 permit 行；regular 行原样保留
        if branch != "permit":
            keep.append(row)
            continue

        codes, metrics = C.degen_codes(body, literal=args.strict_literal)
        if C.degen_codes(body, literal=True)[0]:   # 口径敏感性统计（恒按原始口径算）
            literal_would_drop += 1

        # 安全口径顺带过一遍：SOFT 词（少女/校园/JK/学生…）而无成年声明的 permit 行
        # 不符合红线，不留在任何产出里（原集已经过门控，这里是兜底）
        minor_code = None
        if C.common.soft_hits(body) and not C.common.has_adult_decl(body):
            minor_code = "MINOR_SOFT_NO_DECL"

        if not codes and not minor_code:
            keep.append(row)
            continue

        for c in codes:
            code_cnt[c] += 1
        if minor_code:
            code_cnt[minor_code] += 1
            minor_dropped += 1
        drops.append({
            "line": lineno,
            "branch": "permit",
            "sha256_16": C.sha16(body),
            "chars": len(body),
            "kind": "degenerate" if codes else "minor_soft",
            "codes": sorted(set(codes + ([minor_code] if minor_code else []))),
            "metrics": metrics,
        })

    total_permit = branch_cnt["permit"]
    dropped_permit = len(drops)
    degen_dropped = dropped_permit - minor_dropped
    stats = {
        "generated_at": "2026-11-21",
        "mode": "strict_literal" if args.strict_literal else "operational",
        "input": {"rows": len(rows), "permit": total_permit,
                  "regular": branch_cnt["regular"]},
        "output": {"rows": len(keep), "permit": total_permit - dropped_permit,
                   "regular": branch_cnt["regular"]},
        "dropped": dropped_permit,
        "dropped_degenerate": degen_dropped,
        "dropped_minor_soft": minor_dropped,
        "dropped_ratio_of_permit": C.fmt(dropped_permit / total_permit) if total_permit else 0,
        "codes": dict(code_cnt),
        "sensitivity": {
            "literal_run3_would_drop": literal_would_drop,
            "literal_run3_ratio_of_permit": C.fmt(literal_would_drop / total_permit) if total_permit else 0,
            "note": "按「任意字符连续≥3即弃」的原始口径会多删的 permit 行（多为正常的啊啊啊/啪啪啪/……）",
        },
    }

    v2 = os.path.join(C.OUT_DIR, "nsfw-clean-v2.jsonl")
    dpath = os.path.join(C.OUT_DIR, "drops-degenerate.jsonl")
    if not args.dry_run:
        C.write_jsonl(v2, keep)
        C.write_jsonl(dpath, drops)
        C.write_json(os.path.join(C.WORK, "clean-stats.json"), stats)
        print("[out] %s" % v2)
        print("[out] %s" % dpath)
    print("[stats] kept=%d dropped=%d codes=%s literal_would_drop=%d"
          % (len(keep), dropped_permit, dict(code_cnt), literal_would_drop))


if __name__ == "__main__":
    main()
