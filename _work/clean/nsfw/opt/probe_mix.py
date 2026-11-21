# -*- coding: utf-8 -*-
"""probe_mix.py — 统计 b1v3 实际混配里 nsfw 各任务形态的占比（只读）。"""
import io
import json
import os
import sys
from collections import Counter

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
sys.path.insert(0, os.path.join(ROOT, "_work", "clean", "nsfw", "opt"))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "_shared", "scripts"))
import opt_common as C  # noqa: E402

FILES = [
    os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "b1-combined", "train-b1-v3-s.jsonl"),
    os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "b1-combined", "train-b1-v3.jsonl"),
]
for p in FILES:
    if not os.path.exists(p):
        print("MISS", p)
        continue
    n = 0
    tags = Counter()
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            n += 1
            if C.common.branch_of(o) == "regular":
                tags["gate_regular"] += 1
                continue
            u = C.user_of(o)
            if "接着写" in u or "续写" in u or "继续写" in u or "往下写" in u:
                tags["continue"] += 1
            elif u.startswith("[[NSFW]]"):
                tags["zeroshot"] += 1
            else:
                tags["permit_other"] += 1
    print(os.path.basename(p), "rows", n, dict(tags))
