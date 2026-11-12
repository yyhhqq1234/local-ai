#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mix_by_token_ratio.py — P0② 按 **token/字符份额** 混料（替代按行数混料）

## 为什么换口径（mix-v5 缺陷分析的直接结论）

方案 Y 说「kitty 92% : 2A 8%」——那是**行份额**。
但 `completion_only_loss=True` 只在 assistant 段算 loss，而两段长度差 7 倍：
    kitty  assistant P50 = 200 字符
    2A     assistant P50 = 1401 字符
⇒ 实测 assistant 字符份额是 **kitty 68.87% : 2A 31.13%**，即真实梯度配比 69:31，不是 92:8。
「8% 曝光太小」这个判断从第一秒就建立在错的分母上。

本脚本以 **assistant 字符份额** 为唯一配比口径，并把行份额同时打印以便对照。

## 用法
  python train/lines/_shared/scripts/mix_by_token_ratio.py \
      --kitty train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-bucketed.jsonl \
      --extra train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t1.jsonl \
      --extra train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t2.jsonl \
      --target-share 0.18 --out train/lines/9b-oxcoder/data/_legacy/mix-v6.jsonl
"""
import argparse
import hashlib
import io
import json
import os
import random
import sys


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def load(path, tag):
    rows, bad, tc = [], 0, 0
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            bad += 1
            continue
        if not isinstance(o.get("messages"), list) or not o["messages"]:
            bad += 1
            continue
        a = asst(o)
        if "<tool_call>" in a:
            tc += 1
        o["_mix_src"] = tag
        rows.append(o)
    chars = sum(len(asst(o)) for o in rows)
    return rows, bad, tc, chars


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kitty", required=True)
    ap.add_argument("--extra", action="append", default=[],
                    help="可多次给；这些源的 tool_call 必须为 0（负例不得夹带正例）")
    ap.add_argument("--target-share", type=float, default=0.18,
                    help="extra 合计占 assistant 字符的目标份额，默认 0.18")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ga", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    for p in [args.kitty] + args.extra:
        if not os.path.isfile(p):
            sys.exit("[FATAL] 输入不存在: %s" % p)

    k_rows, k_bad, k_tc, k_chars = load(args.kitty, "kitty")
    e_rows, e_chars, e_bad, e_tc = [], 0, 0, 0
    per = []
    for p in args.extra:
        rs, bad, tc, ch = load(p, os.path.basename(p).replace(".jsonl", ""))
        e_rows += rs
        e_chars += ch
        e_bad += bad
        e_tc += tc
        per.append((os.path.basename(p), len(rs), ch, tc))

    print("[in ] kitty %s  %d 行 · assistant 字符 %d · tool_call 行 %d"
          % (os.path.basename(args.kitty), len(k_rows), k_chars, k_tc))
    for name, n, ch, tc in per:
        print("[in ] extra %-38s %5d 行 · %8d 字符 · tool_call 行 %d%s"
              % (name, n, ch, tc, "  ← 必须为 0" if tc else ""))
    if e_tc:
        sys.exit("[FATAL] extra 源里出现 tool_call（%d 行）——负例集被污染，混料中止" % e_tc)

    # 目标：e_chars / (k_chars + e_chars) = target
    want_e = args.target_share / (1 - args.target_share) * k_chars
    if e_chars > want_e:
        # 抽稀 extra
        ratio = want_e / e_chars
        n_keep = max(1, int(len(e_rows) * ratio))
        random.Random(args.seed).shuffle(e_rows)
        e_rows = e_rows[:n_keep]
        e_chars = sum(len(asst(o)) for o in e_rows)
        print("[adj] extra 超目标，抽稀到 %d 行" % n_keep)
    elif e_chars < want_e:
        print("[warn] extra 只有 %d 字符，达不到 %.0f%% 目标（差 %d 字符）——按现有全量混"
              % (e_chars, 100 * args.target_share, int(want_e - e_chars)))

    rows = k_rows + e_rows
    random.Random(args.seed).shuffle(rows)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fo:
        for o in rows:
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")

    tot_n = len(rows)
    tot_c = k_chars + e_chars
    steps = (tot_n + args.ga - 1) // args.ga
    print("")
    print("[out] %s" % args.out)
    print("      行数 %d（行份额 kitty %.2f%% / extra %.2f%%）"
          % (tot_n, 100.0 * len(k_rows) / tot_n, 100.0 * len(e_rows) / tot_n))
    print("      梯度份额（assistant 字符）kitty %.2f%% / extra %.2f%%  ← 这才是配比"
          % (100.0 * k_chars / tot_c, 100.0 * e_chars / tot_c))
    print("      字符合计 %d · sha16 %s · %d B · seed %d"
          % (tot_c, sha16(args.out), os.path.getsize(args.out), args.seed))
    print("      训练步数 = ceil(%d / ga%d) = %d 步/epoch" % (tot_n, args.ga, steps))


if __name__ == "__main__":
    main()
