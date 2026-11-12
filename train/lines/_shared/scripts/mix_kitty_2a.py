#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mix_kitty_2a.py — 方案 Y（rehearsal）混料：kitty 全量 + 2A 全量，一次训完

背景（TASKPOINT §A6 / 根因 C8）：
  串行阶段训练（先 RE 后 2A）会覆盖前序能力 —— 2A 轮把 RE 命中从 75.0% 打到 10.0%。
  正解是同期共存（rehearsal）：RE 主线数据全量在场，2A 作为约 8% 的增量。

方案 Y 定量：
  kitty  train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-bucketed.jsonl   23718 条（r3 的训练集原样）
  2A     train/lines/9b-oxcoder/data/agent-traj/traj-2a-v4-aug.jsonl                2001 条（体检四绿）
  合计   25719 条（2A 占 7.78%），seed=42 全局打散
  → 25719 / ga4 = 6430 步/epoch（1 epoch）

不做的事（刻意）：
  · 不去重：两组来源不同域，重复即"真实的重复曝光"，由配比决定
  · 不改 messages 正文：任何改写都会让 B11/B12 门禁与训练口径脱钩
  · 不加权重字段：train_qlora9b.py 只读 messages，权重机制在云端训练器才有

用法：
  python train/lines/_shared/scripts/mix_kitty_2a.py                     # 默认输出 train/lines/9b-oxcoder/data/_legacy/mix-v5.jsonl
  python train/lines/_shared/scripts/mix_kitty_2a.py --out <path> --seed 42
"""
import argparse
import hashlib
import io
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # train/
DEF_KITTY = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-bucketed.jsonl")
DEF_2A = os.path.join(ROOT, "data", "agent-traj", "traj-2a-v4-aug.jsonl")
DEF_OUT = os.path.join(ROOT, "data", "mix-v5.jsonl")


def load(path, tag):
    rows, bad = [], 0
    with io.open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
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
            o["_mix_src"] = tag
            rows.append(o)
    return rows, bad


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kitty", default=DEF_KITTY)
    ap.add_argument("--traj", default=DEF_2A)
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ga", type=int, default=4, help="梯度累积步数（只用于算步数）")
    args = ap.parse_args()

    for p in (args.kitty, args.traj):
        if not os.path.isfile(p):
            sys.exit("[FATAL] 输入不存在: %s" % p)

    kitty, kb = load(args.kitty, "kitty")
    traj, tb = load(args.traj, "2a")
    print("[in ] kitty = %s  (%d 条，坏行 %d)" % (os.path.basename(args.kitty), len(kitty), kb))
    print("[in ] 2a    = %s  (%d 条，坏行 %d)" % (os.path.basename(args.traj), len(traj), tb))

    rows = kitty + traj
    random.Random(args.seed).shuffle(rows)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    n = len(rows)
    n2a = sum(1 for o in rows if o["_mix_src"] == "2a")
    steps = (n + args.ga - 1) // args.ga
    print("[out] %s" % args.out)
    print("      行数 %d（kitty %d / 2a %d · 2A 占比 %.2f%%）"
          % (n, n - n2a, n2a, 100.0 * n2a / max(n, 1)))
    print("      sha16 %s · %d B · seed=%d · 打散后首行来源=%s"
          % (sha16(args.out), os.path.getsize(args.out), args.seed, rows[0]["_mix_src"]))
    print("      训练步数 = ceil(%d / ga%d) = %d 步/epoch" % (n, args.ga, steps))


if __name__ == "__main__":
    main()
