#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""路径迁移改写：把脚本/文档里的 train/xxx 引用改到 train/lines/<line>/ 新位置。
只改文本类文件（.py/.sh/.ps1/.mjs/.js/.md/.txt/.yml/.yaml/.toml/.cfg/.ini），
跳过 .git / .venv / node_modules / 权重与数据目录 / *.jsonl / *.json / *.safetensors。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

# 顺序很重要：长路径优先，避免 train/lines/9b-oxcoder/data/eval 被 train/data 之类误替换
MAP = [
    ("train/lines/9b-oxcoder/data/kitty-reverse", "train/lines/9b-oxcoder/data/kitty-reverse"),
    ("train/lines/9b-oxcoder/data/agent-traj",    "train/lines/9b-oxcoder/data/agent-traj"),
    ("train/lines/9b-oxcoder/data/nsfw-gated-v1", "train/lines/9b-oxcoder/data/nsfw-gated-v1"),
    ("train/lines/9b-oxcoder/data/nsfw-gated",    "train/lines/9b-oxcoder/data/nsfw-gated"),
    ("train/lines/9b-oxcoder/data/_chunk-audit",  "train/lines/9b-oxcoder/data/_chunk-audit"),
    ("train/lines/9b-oxcoder/data/eval",          "train/lines/9b-oxcoder/data/eval"),
    ("train/lines/27b-kittyrev/data/versions",      "train/lines/27b-kittyrev/data/versions"),
    ("train/lines/_shared/data/nsfw",          "train/lines/_shared/data/nsfw"),
    ("train/lines/_shared/data/raw",           "train/lines/_shared/data/raw"),
    ("train/lines/9b-oxcoder/models",             "train/lines/9b-oxcoder/models"),
    ("train/lines/9b-oxcoder/out",                "train/lines/9b-oxcoder/out"),
    ("train/lines/27b-kittyrev/local-pack",         "train/lines/27b-kittyrev/local-pack"),
    ("train/lines/27b-kittyrev/kitty-rev",          "train/lines/27b-kittyrev/kitty-rev"),
    ("train/lines/27b-kittyrev/heretic-pareto",     "train/lines/27b-kittyrev/heretic-pareto"),
    ("train/lines/27b-kittyrev/merged",             "train/lines/27b-kittyrev/merged"),
    ("train/lines/27b-kittyrev/quant",              "train/lines/27b-kittyrev/quant"),
    ("train/lines/27b-kittyrev/base",               "train/lines/27b-kittyrev/base"),
    ("train/lines/_shared/scripts",            "train/lines/_shared/scripts"),
    ("train/lines/_shared/tools",              "train/lines/_shared/tools"),
    ("train/lines/_shared/hf",                 "train/lines/_shared/hf"),
]
EXTS = {".py", ".sh", ".ps1", ".mjs", ".js", ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini"}
SKIP_DIR = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", "site-packages"}


def variants(a):
    """同一路径的 / 与 \\ 两种写法"""
    out = {a, a.replace("/", "\\")}
    return out


def main():
    changed = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT).replace("\\", "/")
        if any(s in rel.split("/") for s in SKIP_DIR):
            dirnames[:] = []
            continue
        # 跳过数据/权重目录
        if re.search(r"train/lines/.*/(out|models|local-pack|base|data)/", rel + "/"):
            parts = rel.split("/")
            if len(parts) >= 4 and parts[3] in ("out", "models", "local-pack", "base", "data"):
                # 仍允许扫到 out/ 与 data/ 顶层的 .md 说明文件，但不下钻
                dirnames[:] = [d for d in dirnames if d in ()]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in EXTS:
                continue
            p = os.path.join(dirpath, fn)
            try:
                txt = io.open(p, encoding="utf-8").read()
            except Exception:
                continue
            new = txt
            for old, tgt in MAP:
                for ov in variants(old):
                    tv = tgt if "/" in ov else tgt.replace("/", "\\")
                    if ov in new:
                        new = new.replace(ov, tv)
            if new != txt:
                io.open(p, "w", encoding="utf-8", newline="").write(new)
                changed.append(os.path.relpath(p, ROOT))
    print(f"改写文件 {len(changed)} 个")
    for c in changed[:40]:
        print("  ", c)
    if len(changed) > 40:
        print(f"   … 其余 {len(changed)-40} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
