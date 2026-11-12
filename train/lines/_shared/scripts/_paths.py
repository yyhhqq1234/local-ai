#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""_paths.py —— 双线迁移（train/lines/）后的唯一路径解析源

背景：2026-11-01 训练数据与目录按 AGENTS §3.1 物理迁移到 train/lines/{9b-oxcoder,27b-kittyrev,_shared}。
      但脚本仍按「脚本上级目录 = train」推导 TRAIN，迁移后算出 train/lines/_shared，
      导致 tools / data/versions / kitty-rev/tools / imatrix 四处落空（已实测 MISS）。

用法（脚本头只需一行）：
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _paths import QUANT, GGUF_PY, VERSIONS, IMATRIX, BASE, LOCAL_PACK, KREV, LOGS

约定：所有常量都经过 pick() 真实存在性检查，返回第一个存在的候选；
      全部不存在时返回第一个候选（让报错落在真正的期望位置，便于定位）。
"""
import os

S    = os.path.dirname(os.path.abspath(__file__))          # .../train/lines/_shared/scripts
SH   = os.path.dirname(S)                                   # .../train/lines/_shared
LINES= os.path.dirname(SH)                                  # .../train/lines
TRAIN= os.path.dirname(LINES)                               # .../train
ROOT = os.path.dirname(TRAIN)                               # .../Local-AI
L9   = os.path.join(LINES, "9b-oxcoder")
L27  = os.path.join(LINES, "27b-kittyrev")


def pick(*cands):
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


# ── 共享工具（迁移后在 _shared/tools，老位置 train/tools 仅作兼容）───────────
TOOLS      = pick(os.path.join(SH, "tools"), os.path.join(TRAIN, "tools"))
LC_PY      = os.path.join(TOOLS, "lc", "convert_hf_to_gguf.py")
GGUF_PY    = os.path.join(TOOLS, "lc", "gguf-py")
QUANT      = os.path.join(TOOLS, "llama-cpp-win", "llama-quantize.exe")
IMATRIX_EXE= os.path.join(TOOLS, "llama-cpp-win", "llama-imatrix.exe")
NINFER_AM  = os.path.join(TOOLS, "ninfer-all-master")

# ── 27B 线 ────────────────────────────────────────────────────────────────
BASE       = pick(os.path.join(L27, "base", "Qwen3.8-27B"),
                  os.path.join(TRAIN, "base", "Qwen3.8-27B"))
LOCAL_PACK = pick(os.path.join(L27, "local-pack"), os.path.join(TRAIN, "local-pack"))
MERGED     = pick(os.path.join(L27, "merged"), os.path.join(TRAIN, "merged"))
VERSIONS   = pick(os.path.join(L27, "data", "versions"), os.path.join(TRAIN, "data", "versions"))
KREV       = pick(os.path.join(L27, "kitty-rev"), os.path.join(TRAIN, "kitty-rev"))
SAFE_CONVERT = os.path.join(KREV, "tools", "convert_gguf_safe.py")
MMPROJ     = pick(os.path.join(LOCAL_PACK, "gen3", "gen3-mmproj.gguf"),
                  os.path.join(TRAIN, "local-pack", "gen3", "gen3-mmproj.gguf"))

# 量化输入：imatrix / calib 归 27B 线（当前仍留在 train/data，属于待搬迁遗留）
IMATRIX    = pick(os.path.join(L27, "data", "imatrix-gen2.dat"),
                  os.path.join(SH, "data", "imatrix-gen2.dat"),
                  os.path.join(TRAIN, "data", "imatrix-gen2.dat"))
CALIB      = pick(os.path.join(L27, "data", "calib-gen2v2.txt"),
                  os.path.join(TRAIN, "data", "calib-gen2v2.txt"))

# ── 9B 线 ─────────────────────────────────────────────────────────────────
NSFW_GATED = pick(os.path.join(L9, "data", "nsfw-gated"),
                  os.path.join(SH, "data", "nsfw-gated"),
                  os.path.join(TRAIN, "data", "nsfw-gated"))
EVAL_9B    = pick(os.path.join(L9, "data", "eval"), os.path.join(TRAIN, "data", "eval"))
OUT_9B     = pick(os.path.join(L9, "out"), os.path.join(TRAIN, "out"))

# ── 共享数据 ──────────────────────────────────────────────────────────────
NSFW_SRC   = pick(os.path.join(SH, "data", "nsfw"), os.path.join(TRAIN, "data", "nsfw"))
LEXICON    = pick(os.path.join(NSFW_SRC, "nsfw-lexicon-v9.json"),
                  os.path.join(TRAIN, "data", "nsfw", "nsfw-lexicon-v9.json"))
RAW        = pick(os.path.join(SH, "data", "raw"), os.path.join(TRAIN, "data", "raw"))

# ── 日志 ──────────────────────────────────────────────────────────────────
LOGS       = pick(os.path.join(TRAIN, "logs"), os.path.join(SH, "logs"))


def check(verbose=True):
    """返回 {名字: 是否存在}，verbose 时直接打印。用于迁移后自检。"""
    import sys as _s
    g = {k: v for k, v in globals().items()
         if k.isupper() and isinstance(v, str) and os.path.isabs(v)}
    res = {k: os.path.exists(v) for k, v in g.items()}
    if verbose:
        for k, ok in sorted(res.items()):
            _s.stdout.write(f"  {'OK  ' if ok else 'MISS'} {k:12s} {g[k]}\n")
    return res


if __name__ == "__main__":
    print(f"ROOT  {ROOT}\nTRAIN {TRAIN}\nL9    {L9}\nL27   {L27}\n")
    r = check()
    bad = [k for k, ok in r.items() if not ok]
    print(f"\n{len(r)-len(bad)}/{len(r)} 存在" + (f"，缺失 {bad}" if bad else "，全部就位"))
