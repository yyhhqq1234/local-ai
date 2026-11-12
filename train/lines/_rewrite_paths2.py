#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二轮路径改写：处理 train/data 下遗留散文件已迁走后的引用。
映射：train/data/mix-*.jsonl → 9b/data/_legacy/ · kitty-tool-catalog.json → 9b/data/
      calib-gen2v2.txt / imatrix-gen2.dat → 27b/quant/ · train.example.jsonl → _shared/data/
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
EXTS = {".py", ".sh", ".ps1", ".mjs", ".js", ".md", ".json", ".txt", ".yml", ".yaml"}
SKIP = {".git", ".venv", "node_modules", "__pycache__", "site-packages"}

MIX_TARGETS = ("9b-oxcoder/data/_legacy",)
RULES = [
    (r"train/data/(mix-[A-Za-z0-9_.\-]*\.jsonl\.bak-dedup)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(mix-[A-Za-z0-9_.\-]*\.jsonl)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(_smoke-[A-Za-z0-9_.\-]*\.jsonl)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(_diag-[A-Za-z0-9_.\-]*\.jsonl)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(_bench-[A-Za-z0-9_.\-]*\.json)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/kitty-tool-catalog\.json", "train/lines/9b-oxcoder/data/kitty-tool-catalog.json"),
    (r"train/data/(DATASETS-2A-2B-2C\.json)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(MANIFEST\.json)", "train/lines/9b-oxcoder/data/_legacy/\\1"),
    (r"train/data/(calib-gen2v2\.txt)", "train/lines/27b-kittyrev/quant/\\1"),
    (r"train/data/(imatrix-gen2\.dat)", "train/lines/27b-kittyrev/quant/\\1"),
    (r"train/data/train\.example\.jsonl", "train/lines/_shared/data/train.example.jsonl"),
]


def main():
    changed = 0
    for dp, dns, fns in os.walk(ROOT):
        rel = os.path.relpath(dp, ROOT).replace("\\", "/")
        if any(s in rel.split("/") for s in SKIP):
            dns[:] = []
            continue
        if rel.startswith("train/lines/") and re.search(r"/(out|models|local-pack|base|data)/", rel + "/"):
            parts = rel.split("/")
            if len(parts) >= 4 and parts[3] in ("out", "models", "local-pack", "base", "data"):
                dns[:] = []
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in EXTS:
                continue
            p = os.path.join(dp, fn)
            try:
                txt = io.open(p, encoding="utf-8").read()
            except Exception:
                continue
            new = txt
            for pat, rep in RULES:
                new = re.sub(pat, rep, new)
            if new != txt:
                io.open(p, "w", encoding="utf-8", newline="").write(new)
                changed += 1
    print(f"第二轮改写 {changed} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
