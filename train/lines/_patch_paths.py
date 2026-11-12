#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把脚本里「基于 TRAIN_ROOT 拼旧布局」的路径，改为 _dsh_paths 提供的新常量。
只改路径拼接处，不动其它逻辑；改完打印每个文件的替换条数。
"""
import io
import os
import re
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_shared", "scripts")
sys.path.insert(0, SCRIPTS)
from _dsh_paths import SHARED, L9B, L27B, TRAIN  # noqa: E402

IMPORT_BLOCK = (
    "\ntry:  # 双线目录单一真相源（2026-11-01 迁移后）\n"
    "    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED\n"
    "    TRAIN_ROOT = _TRAIN\n"
    "except Exception:\n"
    "    _L9B = _L27B = _SHARED = None\n"
)

D9 = ("kitty-reverse", "agent-traj", "nsfw-gated", "nsfw-gated-v1", "eval", "_chunk-audit")
D27 = ("versions",)
DS = ("nsfw", "raw")


def rules():
    out = []
    # os.path.join(TRAIN_ROOT, "data", "<sub>"
    for s in D9:
        out.append((f'TRAIN_ROOT, "{s}"'.replace('"', '"'), None))  # placeholder, 不直接用
    out = []
    for s in D9:
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"data"\s*,\s*"(%s)"' % re.escape(s)),
                    r'os.path.join(_L9B, "data", "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/data/(%s)' % re.escape(s)), r'{_L9B}/data/\1'))
    for s in D27:
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"data"\s*,\s*"(%s)"' % re.escape(s)),
                    r'os.path.join(_L27B, "data", "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/data/(%s)' % re.escape(s)), r'{_L27B}/data/\1'))
    for s in DS:
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"data"\s*,\s*"(%s)"' % re.escape(s)),
                    r'os.path.join(_SHARED, "data", "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/data/(%s)' % re.escape(s)), r'{_SHARED}/data/\1'))
    for s in ("models", "out"):
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"(%s)"' % s), r'os.path.join(_L9B, "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/(%s)' % s), r'{_L9B}/\1'))
    for s in ("base", "local-pack", "kitty-rev", "quant", "merged", "heretic-pareto"):
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"(%s)"' % re.escape(s)), r'os.path.join(_L27B, "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/(%s)' % re.escape(s)), r'{_L27B}/\1'))
    for s in ("scripts", "hf", "tools"):
        out.append((re.compile(r'os\.path\.join\(\s*TRAIN_ROOT\s*,\s*"(%s)"' % s), r'os.path.join(_SHARED, "\1"'))
        out.append((re.compile(r'\{TRAIN_ROOT\}/(%s)' % s), r'{_SHARED}/\1'))
    return out


def main():
    R = rules()
    total_files = total_subs = 0
    for fn in sorted(os.listdir(SCRIPTS)):
        if not fn.endswith(".py") or fn == "_dsh_paths.py":
            continue
        p = os.path.join(SCRIPTS, fn)
        txt = io.open(p, encoding="utf-8", errors="ignore").read()
        if "TRAIN_ROOT = os.path.dirname(HERE)" not in txt:
            continue
        new, n = txt, 0
        for pat, rep in R:
            new, k = pat.subn(rep, new)
            n += k
        if "_dsh_paths import" not in new:
            new = new.replace("TRAIN_ROOT = os.path.dirname(HERE)",
                              "TRAIN_ROOT = os.path.dirname(HERE)" + IMPORT_BLOCK, 1)
        if new != txt:
            io.open(p, "w", encoding="utf-8", newline="").write(new)
            total_files += 1
            total_subs += n
            print(f"  {fn}: 路径替换 {n} 处")
    print(f"\n共改写 {total_files} 个脚本 · 路径拼接替换 {total_subs} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
