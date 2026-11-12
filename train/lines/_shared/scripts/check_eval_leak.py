"""泛化集泄漏检查 —— 场景题是否与训练集表述重叠

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么必须有这一步
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-10-28 踩过：`eval_re_heldout.py` 直接从训练集抽样，测出来的是记忆不是能力
（详见 PITFALLS E4）。泛化集虽然人工改写，但如果某条与训练集某条高度相似，
那条的"命中"就是背出来的，会污染整体读数。

判据：**最高相似度 < 0.55** 视为表述无重叠。
实测 36 条的最高值见报告；超 0.55 的条目会指出可疑的训练集原文，供人工改写。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python check_eval_leak.py                          # 默认检查 RE 泛化集
  python check_eval_leak.py --threshold 0.50         # 更严
  python check_eval_leak.py --topk 40                # 每条看更多候选
  exit code: 0 = 通过；1 = 有超阈值条目
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import difflib
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

sys.path.insert(0, HERE)

DEFAULT_DATA = os.path.join(_L9B, "data", "kitty-reverse", "train-kitty-core.jsonl")


def load_users(path):
    out = []
    with io.open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            u = next((m.get("content", "") for m in o.get("messages") or []
                      if m.get("role") == "user"), "")
            if u.strip():
                out.append(u)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="re", choices=["re"],
                    help="检查哪套泛化集（目前只有 re）")
    ap.add_argument("--data", default=DEFAULT_DATA, help="训练集路径")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--topk", type=int, default=20,
                    help="每条先按 quick_ratio 取前 K 个候选再精算")
    args = ap.parse_args()

    from eval_cases_re import CASES

    print("=" * 78)
    print("泛化集泄漏检查 —— %s（%d 条场景）" % (args.cases, len(CASES)))
    print("=" * 78)
    users = load_users(args.data)
    if not users:
        sys.exit("[FATAL] 训练集为空: %s" % args.data)
    print("训练集 user 数 = %d" % len(users))
    print("阈值 = %.2f（最高相似 >= 此值判为泄漏）" % args.threshold)
    print()

    bad = []
    worst = 0.0
    worst_id = ""
    for c in CASES:
        ask = c["ask"]
        # ★ 第一遍：quick_ratio 全量打分后取 topk（不要加门槛过滤！）
        #   踩过：原来写 `if q >= threshold*0.8` 才收进候选，结果大部分条目
        #   没有任何候选 → 精算时 best=0.0，报出来的「0.000」是假的「无重叠」。
        #   正确做法：全部保留，按分数取前 topk，再精算。
        scored = [(difflib.SequenceMatcher(None, ask, u).quick_ratio(), u) for u in users]
        scored.sort(key=lambda x: -x[0])
        top = scored[:args.topk]
        # 第二遍：精算
        best, best_u = 0.0, ""
        for _, u in top:
            r = difflib.SequenceMatcher(None, ask, u).ratio()
            if r > best:
                best, best_u = r, u
        flag = ""
        if best >= args.threshold:
            flag = "  ⚠ 泄漏"
            bad.append((c["id"], best, ask, best_u))
        if best > worst:
            worst, worst_id = best, c["id"]
        print("  %s %-3s 最高相似 %.3f%s" % (c["id"], c["level"], best, flag))

    print()
    print("=" * 78)
    print("结论")
    print("=" * 78)
    print("  全部 %d 条的最高相似度 = %.3f（%s）" % (len(CASES), worst, worst_id))
    if bad:
        print("  ⚠ %d 条超阈值 %.2f，需改写：" % (len(bad), args.threshold))
        for cid, r, ask, u in bad:
            print()
            print("    [%s] 相似 %.3f" % (cid, r))
            print("      场景: %s" % ask[:120])
            print("      训练: %s" % u[:120])
        print()
        print("  → 请改写这些场景的措辞（换说法/换角度），改完重跑本脚本")
        sys.exit(1)

    print("  ✅ 全部低于 %.2f，泛化测试可信" % args.threshold)
    sys.exit(0)


if __name__ == "__main__":
    main()
