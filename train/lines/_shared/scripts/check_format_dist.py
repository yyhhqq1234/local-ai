#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
训练集格式分布体检（E20 的直接产物）

背景 —— 2026-10-30 2A 失败案例：
  训练集 14828 条里 88.8% 完全不含代码块，
  而 SYSTEM_2A 要求「fenced code block」、验收判据要 code_rate >= 80%。
  结果训练后 code_rate 2.5%、avg_cov 30.6%，比不训练（40%/60%）还差。
  训练指标（loss 0.2312 / token_acc 89.5%）全程漂亮 —— 过程健康，产出物没用。

用法：
  python train/lines/_shared/scripts/check_format_dist.py --data <jsonl> \
      [--need-code 0.80] [--len-min 800] [--len-max 1500] [--sample 2000]

输出：格式占比 vs 判据阈值对照表 + PASS/FAIL 结论
退出码：0 = 通过；1 = 不通过（可直接用于 CI / 开训前置检查）
"""
import argparse
import io
import json
import os
import random
import re
import sys
from collections import Counter


def get_text(obj):
    """从各种数据形态里取出 assistant / completion 文本。"""
    # 形态 1：prompt/completion 双列
    c = obj.get("completion")
    if isinstance(c, str) and c.strip():
        return c
    # 形态 2：messages 数组
    msgs = obj.get("messages") or []
    if isinstance(msgs, list):
        parts = []
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "assistant":
                ct = m.get("content")
                if isinstance(ct, str):
                    parts.append(ct)
                elif isinstance(ct, list):
                    for blk in ct:
                        if isinstance(blk, dict) and isinstance(blk.get("text"), str):
                            parts.append(blk["text"])
        if parts:
            return "".join(parts)
    # 形态 3：conversations（sharegpt）
    conv = obj.get("conversations") or []
    if isinstance(conv, list):
        parts = [m.get("value", "") for m in conv
                 if isinstance(m, dict) and m.get("from") in ("gpt", "assistant")]
        if parts:
            return "".join(parts)
    return ""


FENCE_RE = re.compile(r"```")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")     # 标识符粗估
PATH_RE = re.compile(r"[\w./\\-]+\.(py|js|ts|c|cpp|h|hpp|go|rs|java|cs|sh|ps1|json|yaml|yml)")

# 角色标记污染（B11）—— 训练数据 assistant 正文里**绝不该**出现这些，
# 角色由 chat template 管理。出现即污染，模型会学到复读它导致输出崩坏。
MARKS = (
    "【assistant】", "【user】", "【system】",
    "<|assistant|>", "<|user|>", "<|system|>",
    "### Assistant:", "### User:", "### System:",
    "ASSISTANT:", "USER:",
)

# 语义污染（B12）—— user 字段应当是「问题描述」，不该是 agent 执行日志。
# 出现这些 = 轨迹被按 token 固定切窗，切点落在轨迹中间，user 变成了上一窗的尾巴。
LOG_MARKS = (
    "<carry_over>", "[Command finished", "[The command completed",
    "[Current working directory:", "[Python interpreter:",
    "[CALL ", "【observation】",
)


def get_user(obj):
    msgs = obj.get("messages") or []
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            ct = m.get("content")
            if isinstance(ct, list):
                return "".join(b.get("text", "") for b in ct if isinstance(b, dict))
            return ct or ""
    p = obj.get("prompt")
    return p if isinstance(p, str) else ""


def pct(x, n):
    return 100.0 * x / n if n else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="训练集 jsonl")
    ap.add_argument("--need-code", type=float, default=0.80,
                    help="判据要求含代码块占比（默认 0.80）")
    ap.add_argument("--need-ident", type=float, default=0.80,
                    help="判据要求含具体标识符占比（默认 0.80）")
    ap.add_argument("--len-min", type=int, default=800)
    ap.add_argument("--len-max", type=int, default=1500)
    ap.add_argument("--sample", type=int, default=0,
                    help="只抽 N 条体检（0 = 全量）")
    args = ap.parse_args()

    if not os.path.isfile(args.data):
        sys.exit("[FATAL] 文件不存在: %s" % args.data)

    n = 0
    has_fence = 0          # ``` 出现 >= 2 次（成对）
    has_ident = 0          # 含 >= 3 个标识符
    has_path = 0           # 含文件路径
    has_mark = 0           # 含角色标记（应为 0）
    mark_total = 0
    has_log = 0            # user 含 agent 日志碎片（应为 0）
    fence_hist = Counter()
    lens = []
    empty = 0

    lines = open(args.data, encoding="utf-8").read().split("\n")
    lines = [l for l in lines if l.strip()]
    if args.sample and len(lines) > args.sample:
        random.seed(42)
        lines = random.sample(lines, args.sample)

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        text = get_text(obj)
        if not text.strip():
            empty += 1
            continue
        n += 1
        fc = len(FENCE_RE.findall(text))
        fence_hist[min(fc, 4)] += 1
        if fc >= 2:
            has_fence += 1
        if len(set(IDENT_RE.findall(text))) >= 3:
            has_ident += 1
        if PATH_RE.search(text):
            has_path += 1
        mc = sum(text.count(m) for m in MARKS)
        if mc:
            has_mark += 1
            mark_total += mc
        u = get_user(obj)
        if u and any(m in u for m in LOG_MARKS):
            has_log += 1
        lens.append(len(text))

    if not n:
        sys.exit("[FATAL] 没有解析出任何 assistant/completion 文本")

    lens.sort()
    p50 = lens[len(lens) // 2]
    p90 = lens[int(len(lens) * 0.9)]
    p99 = lens[min(len(lens) - 1, int(len(lens) * 0.99))]
    in_range = sum(1 for x in lens if args.len_min <= x <= args.len_max)

    code_pct = has_fence / n
    ident_pct = has_ident / n
    in_range_pct = in_range / n

    print("=" * 72)
    print("训练集格式分布体检 —— %s" % os.path.basename(args.data))
    print("=" * 72)
    print("样本数        : %d（空文本 %d 条已跳过）" % (n, empty))
    print()
    print("%-22s %10s %10s   %s" % ("指标", "实测", "要求", "判定"))
    print("-" * 72)
    ok_code = code_pct >= args.need_code
    ok_ident = ident_pct >= args.need_ident
    ok_len = in_range_pct >= 0.50          # 过半样本落在目标区间即算过
    ok_mark = (has_mark == 0)              # 角色标记必须 0，一票否决
    ok_log = (has_log == 0)                # user 日志碎片必须 0，一票否决
    print("%-22s %9.1f%% %9s   %s" % (
        "含角色标记(污染)", 100 * has_mark / n, "0%",
        "PASS" if ok_mark else "FAIL(致命)"))
    print("%-22s %9.1f%% %9s   %s" % (
        "user含日志碎片(B12)", 100 * has_log / n, "0%",
        "PASS" if ok_log else "FAIL(致命)"))
    print("%-22s %9.1f%% %9.0f%%   %s" % (
        "含完整代码块(```>=2)", 100 * code_pct, 100 * args.need_code,
        "PASS" if ok_code else "FAIL"))
    print("%-22s %9.1f%% %9.0f%%   %s" % (
        "含具体标识符(>=3个)", 100 * ident_pct, 100 * args.need_ident,
        "PASS" if ok_ident else "FAIL"))
    print("%-22s %9.1f%% %9s   %s" % (
        "长度落在[%d,%d]" % (args.len_min, args.len_max),
        100 * in_range_pct, ">=50%",
        "PASS" if ok_len else "FAIL"))
    print("%-22s %9.1f%% %9s   %s" % ("含文件路径", 100 * has_path / n, "(参考)", "-"))
    print("-" * 72)
    print("长度分布      : P50=%d  P90=%d  P99=%d  max=%d" % (p50, p90, p99, lens[-1]))
    print("fence 计数分布: 0个=%d  1个=%d  2个=%d  3个=%d  >=4个=%d" % (
        fence_hist[0], fence_hist[1], fence_hist[2], fence_hist[3], fence_hist[4]))
    print()

    allok = ok_code and ok_ident and ok_len and ok_mark and ok_log
    if allok:
        print("总判定：PASS —— 格式分布满足判据要求")
    else:
        print("总判定：FAIL —— 不要开训，先修数据")
        print()
        print("修法：")
        if not ok_log:
            print("  ⛔ user 含 agent 日志碎片 %d 条（要求 0）" % has_log)
            print("     → 轨迹被按 token 固定切窗，切点落在轨迹中间，user 变成上一窗的尾巴")
            print("     → 特征：含 <carry_over> / [Command finished / [Current working directory:")
            print("       且 user 长度 P10/P50/P90 高度接近（固定切窗特征）")
            print("     → 修法：从**未切分**的原始轨迹重新提取，不要从切片里救")
            print("       见 train/lines/_shared/scripts/extract_2a_from_traj.py 与 PITFALLS B12")
        if not ok_mark:
            print("  ⛔ 角色标记污染 %d 条 / 共 %d 个（要求 0）" % (has_mark, mark_total))
            print("     → 训练数据 assistant 正文里不该出现角色标记，角色由 chat template 管理")
            print("     → 2026-10-30 2A 死因：66.3% 样本含【assistant】，模型学会复读它，")
            print("       输出变成【assistant】【assistant】…无限循环，三项指标同时崩坏")
            print("     → 修法：txt = txt.replace(mark, '') 后 re.sub(r'[ \\t]{2,}', ' ', txt).strip()")
        if not ok_code:
            print("  · 代码块占比 %.1f%% < 要求 %.0f%%，差 %.1f 个百分点" % (
                100 * code_pct, 100 * args.need_code,
                100 * (args.need_code - code_pct)))
            print("    → 判据要求什么格式，训练集就该有这个格式，且占比 >= 判据阈值")
        if not ok_ident:
            print("  · 标识符覆盖率 %.1f%% < 要求 %.0f%%，会被 entity_cov 判据打回" % (
                100 * ident_pct, 100 * args.need_ident))
        if not ok_len:
            print("  · 长度中位 %d，只有 %.0f%% 落在 [%d,%d]" % (
                p50, 100 * in_range_pct, args.len_min, args.len_max))
            print("    → 长篇散文会把具体标识符冲散，信息密度优先于篇幅")
            print("    → 参见 2026-10-30 2A 失败：P50=2444 的散文，code_rate 训成 2.5%")
    print()
    print("参考：train/PITFALLS.md 的 E20（数据格式分布与判据口径不符）")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
