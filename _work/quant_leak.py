# -*- coding: utf-8 -*-
"""精确量化：门控训练集与门控评测集的重合到底影响多少评测题

判据：训练集 user 前 100 字命中评测集 user 前 100 字 ⇒ 该评测题「素材已见」
"""
import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
GATE = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train.jsonl")
EVAL_DIR = os.path.join(L9B, "data", "eval")


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
    return [u for u in out if u]


# 训练集：head -> 行数
train_heads = Counter()
for line in io.open(GATE, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    for u in users_of(json.loads(line)):
        if len(u) >= 20:
            train_heads[u[:100]] += 1

print("训练集 user 头部去重：%d 种" % len(train_heads))
print()
total_hit = 0
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        p = os.path.join(d, fn)
        hits, n = [], 0
        for lineno, line in enumerate(io.open(p, encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            o = json.loads(line)
            us = users_of(o)
            for u in us:
                if len(u) >= 20 and u[:100] in train_heads:
                    hits.append((lineno, u[:60].replace("\n", "⏎")))
                    break
        if hits:
            total_hit += len(hits)
            print("%-24s 命中 %d / %d  (%.1f%%)"
                  % ("%s/%s" % (split, fn), len(hits), n, len(hits) * 100.0 / n))
            for ln, head in hits[:4]:
                print("      行 %-6d %s…" % (ln, head))
        else:
            print("%-24s 命中 0 / %d  OK" % ("%s/%s" % (split, fn), n))
print()
print("评测集合计命中 %d 条" % total_hit)

# 反向：训练集里有多少行来自评测素材（含变体）
uniq_train_leak = sum(1 for h, c in train_heads.items() if False)
print()
print("说明：训练集 32174 行 / %d 种头部 ⇒ 大量变体共用同一素材，"
      "评测命中数才是有效口径" % len(train_heads))
