# -*- coding: utf-8 -*-
"""量化：门控训练集里「与评测素材同头」的行数有多少（决定清洗代价）"""
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
    return [u for u in out if len(u) >= 20]


# 1) 收集被污染头部
bad_heads = {}
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        for lineno, line in enumerate(io.open(os.path.join(d, fn), encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            for u in users_of(json.loads(line)):
                bad_heads.setdefault(u[:100], "%s/%s:%d" % (split, fn, lineno))

print("被污染的素材头部：%d 种" % len(bad_heads))
print()

# 2) 统计训练集里命中的行
hit_rows, kinds = [], Counter()
for lineno, line in enumerate(io.open(GATE, encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    for u in users_of(o):
        if u[:100] in bad_heads:
            hit_rows.append((lineno, bad_heads[u[:100]], u[:50].replace("\n", "⏎")))
            a = "".join(str(m.get("content", "")) for m in o.get("messages", [])
                        if m.get("role") == "assistant")
            kinds["拒写" if len(a) < 200 else "正常答"] += 1
            break

print("训练集命中行数：%d / 32174 (%.2f%%)"
      % (len(hit_rows), len(hit_rows) * 100.0 / 32174))
print("其中类型分布：%s" % dict(kinds))
print()
for ln, src, head in hit_rows[:20]:
    print("  行 %-6d ← %-22s %s…" % (ln, src, head))
if len(hit_rows) > 20:
    print("  ... 共 %d 行" % len(hit_rows))
