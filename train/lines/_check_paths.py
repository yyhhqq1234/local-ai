#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""路径失效体检：扫描脚本/文档里的路径字面量，逐条验证是否仍然存在。
输出：缺失清单（按文件分组）+ 旧路径残留（指向已迁移的旧位置）。
"""
import io
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

SCAN_DIRS = ["train/lines/_shared/scripts", "train/lines/27b-kittyrev/kitty-rev",
             "train/lines/9b-oxcoder", "plugins", "."]
EXTS = {".py", ".sh", ".ps1", ".mjs", ".js"}
SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "site-packages"}
SKIP_PATH_PARTS = {"out", "models", "local-pack", "base", "data", "eval", "logs", "tools", "hf"}

# 路径字面量：以 train/ data/ models/ 等开头的相对路径
PAT = re.compile(r"(?<![A-Za-z0-9_.\-/])((?:train|data|models|plugins|ninfer-csunx|docs|_work|_research)/[A-Za-z0-9_.\-/*]+)")
# 旧位置（迁移后应不存在）
OLD = ("train/models", "train/out", "train/data/", "train/base", "train/local-pack",
       "train/kitty-rev", "train/scripts", "train/hf", "train/tools", "train/eval",
       "train/merged", "train/quant", "train/heretic-pareto")


def iter_files():
    seen = set()
    for d in SCAN_DIRS:
        if not os.path.isdir(d):
            continue
        for dp, dns, fns in os.walk(d):
            rel = os.path.relpath(dp, ROOT).replace("\\", "/")
            parts = rel.split("/")
            if any(p in SKIP_PARTS for p in parts):
                dns[:] = []
                continue
            # 不深入数据/权重目录（只看脚本与文档）
            if len(parts) >= 3 and parts[0] == "train" and parts[1] == "lines" and parts[3:4] and parts[3] in SKIP_PATH_PARTS:
                dns[:] = []
            for fn in fns:
                if os.path.splitext(fn)[1].lower() not in EXTS:
                    continue
                p = os.path.join(dp, fn)
                if p in seen:
                    continue
                seen.add(p)
                yield p


def main():
    missing, stale = defaultdict(list), defaultdict(list)
    checked = 0
    for p in iter_files():
        try:
            txt = io.open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        for m in set(PAT.findall(txt)):
            lit = m.rstrip(".")
            if "*" in lit or lit.endswith("/"):
                base = lit.rstrip("/*")
                if not os.path.exists(base):
                    missing[rel].append(lit)
                checked += 1
                continue
            checked += 1
            if not os.path.exists(lit):
                # 允许「运行时才创建的产物路径」（out/ 下、logs/ 下）
                if re.search(r"(^|/)(out|logs)/", lit) or lit.startswith("train/logs/"):
                    continue
                missing[rel].append(lit)
        for o in OLD:
            if o in txt:
                stale[rel].append(o)

    print(f"扫描文件 {len(set(iter_files()))} 个 · 路径字面量 {checked} 处\n")
    print("== 1) 指向不存在的路径 ==")
    if not missing:
        print("  （无）")
    for f, lits in sorted(missing.items()):
        print(f"  {f}")
        for l in sorted(set(lits))[:8]:
            print(f"      ✗ {l}")
    print("\n== 2) 旧位置残留（迁移后应已不存在）==")
    if not stale:
        print("  （无）")
    for f, lits in sorted(stale.items()):
        print(f"  {f}: {', '.join(sorted(set(lits)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
