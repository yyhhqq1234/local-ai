# -*- coding: utf-8 -*-
"""2A 数据 system 替换 —— 方案 A

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么换
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2A 数据（16195 条）的 system 94.4% 是
    "You are OpenHands agent, a helpful AI assistant that can interact with a computer."
但它的 assistant 是**长代码分析文本**（P50 2476 字符，全量仅 3 条含 <tool_call>，0 条多轮）。

这个 system 会触发 base 模型（Qwen3.5-9B）预训练里的 OpenHands agent 记忆，
模型于是去调 `read` 工具而不是写分析 —— 与数据的期望行为冲突。

实测基线（system 不改）：
    实体覆盖 24.8% / 代码块完整率 2.5%
    resp 原文：<tool_call>{"name": "read", "path": ".../parser.py"}</tool_call>

方案 A：把 system 换成「资深工程师」设定，与 assistant 的实际内容对齐。
system 的唯一真相源在 `eval_2a_code.py` 的 SYSTEM_2A（训练与评测必须用同一个）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python replace_2a_system.py --dry-run          # 只统计，不写
  python replace_2a_system.py                     # 写 train/lines/9b-oxcoder/data/agent-traj/traj-2a-v2.jsonl
  # 然后重新分桶（system 变长，长度分布变了）：
  python bucket_by_length.py \
      --in  train/lines/9b-oxcoder/data/agent-traj/traj-2a-v2.jsonl \
      --out train/lines/9b-oxcoder/data/agent-traj/traj-2a-v2-bucketed.jsonl --bucket 128
"""
import argparse
import collections
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

from sys_prompts import SYSTEM_2A   # noqa: E402  单一真相源（不依赖 torch）

SRC = os.path.join(_L9B, "data", "agent-traj", "traj-all-capped.jsonl")
OUT = os.path.join(_L9B, "data", "agent-traj", "traj-2a-v2.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=" * 78)
    print("2A 数据 system 替换（方案 A）")
    print("=" * 78)
    print("src: %s" % args.src)
    print("新 system（%d 字符）:" % len(SYSTEM_2A))
    for ln in SYSTEM_2A.split("\n"):
        print("    " + ln)
    print()

    seen = collections.Counter()
    n = replaced = 0
    rows = []
    with io.open(args.src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            o = json.loads(line)
            hit = False
            for m in o.get("messages") or []:
                if m.get("role") == "system":
                    seen[(m.get("content") or "")[:70]] += 1
                    if m.get("content") != SYSTEM_2A:
                        m["content"] = SYSTEM_2A
                        hit = True
                    break
            if hit:
                replaced += 1
            rows.append(o)

    print("扫描 %d 条 | 替换 %d 条" % (n, replaced))
    print("原 system 种类 top5：")
    for k, v in seen.most_common(5):
        print("  %6d  %s" % (v, k.replace("\n", " ")[:66]))

    if args.dry_run:
        print("\n[dry-run] 不落盘")
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("\n→ 落盘 %s（%d 条）" % (args.out, len(rows)))
    print("  下一步重新分桶：")
    print("  python bucket_by_length.py --in %s --out %s --bucket 128"
          % (args.out, args.out.replace(".jsonl", "-bucketed.jsonl")))


if __name__ == "__main__":
    main()
