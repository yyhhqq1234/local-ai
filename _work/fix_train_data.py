# -*- coding: utf-8 -*-
"""训练数据定点修复（默认 dry-run，加 --apply 才落盘）

修三类问题：
  F1 门控腿评测污染：训练集 15 行与 val/test nsfw-gate 素材同头 ⇒ 删（损失 0.05%）
  F2 RE 腿编造工具名：`kitty_cedump` 是不存在的名字（真名 kitty_ce / kitty_dump）
     ⇒ 保守改写为 kitty_ce，并记原文便于回溯
  F3 完全重复行：opt-in（--dedup），默认不动 —— 重复不污染评测，只影响训练权重分布

用法：
  python _work/fix_train_data.py                 # 只看会改什么
  python _work/fix_train_data.py --apply         # 落盘（F1+F2）
  python _work/fix_train_data.py --apply --dedup # 落盘且去重
输出写新文件，原文件不改：
  nsfw-gated/train-2b-gated-v4b-train-deleak.jsonl
  _legacy/mix-z-re-v4-fixed.jsonl
"""
import argparse
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
GATE_IN = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train.jsonl")
GATE_OUT = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train-deleak.jsonl")
RE_IN = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4.jsonl")
RE_OUT = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
EVAL_DIR = os.path.join(L9B, "data", "eval")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--dedup", action="store_true")
args = ap.parse_args()


def users_of(o):
    out = []
    for k in ("user", "prompt", "question", "query", "input"):
        v = o.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    msgs = o.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if m.get("role") == "user":
                out.append(str(m.get("content", "")).strip())
    return [u for u in out if len(u) >= 20]


# ── F1：污染头部集合 ────────────────────────────────────────────────
poison = set()
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        for line in io.open(os.path.join(d, fn), encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            for u in users_of(json.loads(line)):
                poison.add(u[:100])
print("[F1] 评测素材头部基准：%d 种" % len(poison))

print("=" * 88)
print("[F1] 门控腿 %s" % os.path.basename(GATE_IN))
print("=" * 88)
kept, dropped = [], []
seen = set()
dups = 0
for lineno, line in enumerate(io.open(GATE_IN, encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    hit = any(u[:100] in poison for u in users_of(o))
    if hit:
        dropped.append(lineno)
        continue
    if args.dedup:
        if line in seen:
            dups += 1
            continue
        seen.add(line)
    kept.append(line)
print("  读入 32174 行 → 保留 %d · 删污染 %d · 去重再删 %d"
      % (len(kept), len(dropped), dups))
print("  删除行号：%s" % dropped)

# ── F2：RE 腿编造工具名 ────────────────────────────────────────────
print()
print("=" * 88)
print("[F2] RE 腿 %s" % os.path.basename(RE_IN))
print("=" * 88)
FAKE_MAP = [("kitty_cedump", "kitty_ce")]
fixed_lines, fix_cnt = [], Counter()
re_seen = set()
re_dup = 0
for lineno, line in enumerate(io.open(RE_IN, encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    orig = line
    for bad, good in FAKE_MAP:
        if bad in line:
            cnt = line.count(bad)
            line = line.replace(bad, good)
            fix_cnt["%s→%s" % (bad, good)] += cnt
    if line != orig:
        print("  行 %-6d 已改写" % lineno)
    if args.dedup:
        if line in re_seen:
            re_dup += 1
            continue
        re_seen.add(line)
    fixed_lines.append(line)
print("  改写统计：%s" % dict(fix_cnt) if fix_cnt else "  无需改写")
print("  去重：删 %d 行" % re_dup)
print("  行数 %d" % len(fixed_lines))

# ── 落盘 ───────────────────────────────────────────────────────────
print()
if not args.apply:
    print("★ dry-run：未写任何文件。加 --apply 落盘。")
    sys.exit(0)

with io.open(GATE_OUT, "w", encoding="utf-8", newline="\n") as f:
    for ln in kept:
        f.write(ln + "\n")
with io.open(RE_OUT, "w", encoding="utf-8", newline="\n") as f:
    for ln in fixed_lines:
        f.write(ln + "\n")
print("已写：")
print("  %s  (%d 行)" % (GATE_OUT, len(kept)))
print("  %s  (%d 行)" % (RE_OUT, len(fixed_lines)))
