# -*- coding: utf-8 -*-
"""calc_v4.py — 体积/token 估算（只读）。"""
import io
import json
import os
import sys

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
sys.path.insert(0, os.path.join(ROOT, "_work", "clean", "nsfw", "opt"))
import opt_common as C  # noqa: E402

OPT = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated", "cleaned", "opt")
FILES = ["nsfw-zeroshot-v4.jsonl", "nsfw-continue-v4.jsonl", "nsfw-frontload-v4.jsonl"]
tot_rows = tot_chars = 0
for fn in FILES:
    rows = 0
    chars = 0
    with io.open(os.path.join(OPT, fn), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            rows += 1
            chars += sum(len(m.get("content") or "") for m in o["messages"])
    tot_rows += rows
    tot_chars += chars
    print("%-26s rows=%d chars=%d tok≈%.2fM" % (fn, rows, chars, chars * 0.72 / 1e6))
print("TOTAL rows=%d chars=%d tok≈%.2fM" % (tot_rows, tot_chars, tot_chars * 0.72 / 1e6))
print("2000 行按 45:40:15 → 900/800/300 ≈ %.2fM tok" % (tot_chars / tot_rows * 2000 * 0.72 / 1e6))
