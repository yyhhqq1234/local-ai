#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 2A 混比数据集 —— 按 token 配比（不是按条数）

背景：
  kitty core 5602 条，p50 仅 177 token → 合计 1.32 M token
  轨迹切分后 17553 段，合计 88.4 M token（平均 5000 token/段）
  若按条数 7:3 混，轨迹会占 95% 的 token，kitty 的 RE 能力被淹没。

做法：
  目标 token 配比 kitty : 轨迹 = 7 : 3（可调 --ratio）
  先算两侧单条平均 token，反推需要多少条轨迹才能达到 3/10 的 token 占比，
  多余轨迹按确定性种子下采样（不用随机，保证可复现）。

用法：
  python build_mix_2a.py --ratio 0.7 --out train/lines/9b-oxcoder/data/_legacy/mix-2a.jsonl
  python build_mix_2a.py --ratio 0.5 --out train/lines/9b-oxcoder/data/_legacy/mix-2a-5050.jsonl --audit
"""

import argparse
import io
import json
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")

KITTY = "train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl"
TRAJ = [
    "train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-8k-chunk4096.jsonl",
    "train/lines/9b-oxcoder/data/agent-traj/deepswe/deepswe-8k-chunk4096.jsonl",
    "train/lines/9b-oxcoder/data/agent-traj/swe-rebench/rebench-8k-chunk4096.jsonl",
]
# swe-16k 单独作为 2C 长上下文阶段，不进 2A


def count_tokens(path, tok, limit=None):
    """返回 (行数, 总token, 样本列表[(行号, token数)])"""
    rows = []
    total = 0
    with io.open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            msgs = o.get("messages")
            if not isinstance(msgs, list):
                continue
            t = sum(len(tok.encode(m["content"], add_special_tokens=False)) for m in msgs) + 64
            rows.append((i, t))
            total += t
            if limit and len(rows) >= limit:
                break
    return len(rows), total, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.7, help="（仅 --strict-token 时生效）kitty 的 token 占比")
    ap.add_argument("--kitty-repeat", type=int, default=3,
                    help="kitty 重复轮数（默认 3）。数据量只有 1.51 M token，靠重复来加权")
    ap.add_argument("--strict-token", action="store_true",
                    help="严格按 token 占比配比（会砍掉大量轨迹，导致步数不足，一般不用）")
    ap.add_argument("--traj-ratio", type=float, default=None,
                    help="显式指定轨迹条数占比（覆盖默认的全量轨迹）")
    ap.add_argument("--out", default="train/lines/9b-oxcoder/data/_legacy/mix-2a.jsonl")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--audit", action="store_true", help="只统计不写盘")
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer)

    print("统计 kitty ...", flush=True)
    n_k, t_k, rows_k = count_tokens(KITTY, tok, limit=600)
    avg_k = t_k / n_k
    # 采样只用于估平均值，总量要按全量行数算（否则需要多少轨迹会算错一个数量级）
    n_k_all = 0
    with io.open(KITTY, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n_k_all += 1
    print("  kitty: 全量 %d 条，采样 %d 条 平均 %.0f token/条 → 总约 %.2f M token"
          % (n_k_all, n_k, avg_k, n_k_all * avg_k / 1e6), flush=True)

    print("统计轨迹 ...", flush=True)
    traj_files = []
    n_traj_total = 0
    for p in TRAJ:
        if not os.path.exists(p):
            print("  [跳过] 不存在:", p, flush=True)
            continue
        n, t, _ = count_tokens(p, tok, limit=400)
        avg = t / n
        # 全量行数（只数行，不 encode）
        cnt = 0
        with io.open(p, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    cnt += 1
        n_traj_total += cnt
        print("  %-52s 全量 %6d 段 采样平均 %.0f token/段" % (os.path.basename(p), cnt, avg), flush=True)
        traj_files.append((p, n, t, avg))

    avg_t = sum(a for _, _, _, a in traj_files) / len(traj_files)
    print("  轨迹综合平均 %.0f token/段，全量 %d 段" % (avg_t, n_traj_total), flush=True)

    # 目标：kitty token 占 ratio，轨迹占 1-ratio
    # ★ 关键约束：kitty 全量只有 1.51 M token，若按 token 7:3 配比，总量只剩 2.16 M
    #   （33 步），远不够训练。所以实际用 **epoch 配比**：kitty 重复 N 轮，
    #   轨迹 1 轮全量。这样既有足够步数，又让 kitty 的 RE 范式被重复强化 N 次。
    kitty_tokens = n_k_all * avg_k * args.kitty_repeat
    traj_tokens = n_traj_total * avg_t
    if args.traj_ratio is not None:
        n_traj_need = int(n_k_all * args.traj_ratio / (1 - args.traj_ratio))
        mode = "按条数 %.3f（强制）" % args.traj_ratio
    elif args.strict_token:
        # kitty_tokens / (kitty_tokens + n * avg_t) = ratio
        n_traj_need = int(kitty_tokens * (1 - args.ratio) / (args.ratio * avg_t))
        mode = "严格按 token %.2f（会牺牲步数）" % args.ratio
    else:
        # 默认：轨迹全量 + kitty 重复 N 轮
        n_traj_need = n_traj_total
        mode = "epoch 配比（kitty ×%d + 轨迹全量）" % args.kitty_repeat

    print("", flush=True)
    print("目标配比: %s" % mode, flush=True)
    print("  需要轨迹约 %d 段（总可用 %d 段）" % (n_traj_need, n_traj_total), flush=True)

    if n_traj_need >= n_traj_total:
        print("  ⚠ 可用轨迹不足，全部使用", flush=True)
        n_traj_need = n_traj_total

    # 确定性下采样：每个文件按同样比例抽取
    keep_ratio = n_traj_need / n_traj_total
    rng = random.Random(args.seed)

    out_lines = []
    n_kitty_written = 0
    n_traj_written = 0

    # kitty 全量 × kitty_repeat 轮
    kitty_lines = []
    with io.open(KITTY, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                kitty_lines.append(line if line.endswith("\n") else line + "\n")
    for _ in range(max(1, args.kitty_repeat)):
        out_lines.extend(kitty_lines)
        n_kitty_written += len(kitty_lines)

    # 轨迹按比例抽
    for p in TRAJ:
        if not os.path.exists(p):
            continue
        with io.open(p, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                if rng.random() < keep_ratio:
                    out_lines.append(line if line.endswith("\n") else line + "\n")
                    n_traj_written += 1

    rng.shuffle(out_lines)

    # 实际 token 统计（抽样估算，避免全量 encode 太慢）
    est_k = n_kitty_written * avg_k
    est_t = n_traj_written * avg_t
    est_total = est_k + est_t

    print("", flush=True)
    print("=" * 66, flush=True)
    print("行数: kitty %d + 轨迹 %d = %d" % (n_kitty_written, n_traj_written, len(out_lines)), flush=True)
    print("token(估): kitty %.2f M (%.1f%%) + 轨迹 %.2f M (%.1f%%) = %.2f M"
          % (est_k / 1e6, est_k / est_total * 100, est_t / 1e6, est_t / est_total * 100, est_total / 1e6),
          flush=True)
    print("步数(accum16, ctx4096): %d" % int(est_total / (4096 * 16)), flush=True)
    print("时长 @30s/步: %.1f h   @47s/步: %.1f h"
          % (est_total / (4096 * 16) * 30 / 3600, est_total / (4096 * 16) * 47 / 3600), flush=True)

    if args.audit:
        print("\n[a 通知] --audit 模式，未写盘", flush=True)
        return

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        f.writelines(out_lines)
    print("\n→ %s" % args.out, flush=True)


if __name__ == "__main__":
    main()
