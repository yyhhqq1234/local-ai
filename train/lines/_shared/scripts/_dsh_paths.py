#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""_dsh_paths.py —— 双线目录的单一真相源（脚本专用）

背景：2026-11-01 把 train/{models,out,data,...} 物理迁移到
      train/lines/{9b-oxcoder,27b-kittyrev,_shared}/ 后，
      原本用「脚本自身位置」推导 TRAIN_ROOT 的脚本会推到 train/lines/_shared（错），
      统一改为从这里 import，避免每个脚本各写一份推导。

位置关系：
    <repo>/train/lines/_shared/scripts/_dsh_paths.py
      ↑ _shared ↑ lines ↑ train ↑ repo
"""
import os

SCRIPTS = os.path.dirname(os.path.abspath(__file__))          # .../train/lines/_shared/scripts
SHARED = os.path.dirname(SCRIPTS)                              # .../train/lines/_shared
LINES = os.path.dirname(SHARED)                                # .../train/lines
TRAIN = os.path.dirname(LINES)                                 # .../train
ROOT = os.path.dirname(TRAIN)                                  # repo root

L9B = os.path.join(TRAIN, "lines", "9b-oxcoder")
L27B = os.path.join(TRAIN, "lines", "27b-kittyrev")

# 9B 常用子目录
M9B_MODELS = os.path.join(L9B, "models")
M9B_OUT = os.path.join(L9B, "out")
M9B_DATA = os.path.join(L9B, "data")

# 27B 常用子目录
M27B_BASE = os.path.join(L27B, "base")
M27B_PACK = os.path.join(L27B, "local-pack")
M27B_DATA = os.path.join(L27B, "data")

# 共享
SH_DATA = os.path.join(SHARED, "data")

# 旧逻辑名 → 新位置（供 remap 使用）
_DATA_9B = {"kitty-reverse", "agent-traj", "nsfw-gated", "nsfw-gated-v1", "eval", "_chunk-audit"}
_DATA_27B = {"versions"}
_DATA_SHARED = {"nsfw", "raw"}


def data_root(sub):
    """把旧 TRAIN_ROOT/data/<sub> 映射到新位置"""
    if sub in _DATA_9B:
        return os.path.join(M9B_DATA, sub)
    if sub in _DATA_27B:
        return os.path.join(M27B_DATA, sub)
    if sub in _DATA_SHARED:
        return os.path.join(SH_DATA, sub)
    return os.path.join(M9B_DATA, sub)      # 默认归 9B


def remap(path):
    """把按旧布局拼出来的绝对路径改写到新布局（best-effort）"""
    p = str(path).replace("\\", "/")
    legacy = TRAIN.replace("\\", "/") + "/"
    if not p.startswith(legacy):
        return path
    tail = p[len(legacy):]
    seg = tail.split("/")
    head = seg[0] if seg else ""
    if head == "data" and len(seg) > 1:
        return data_root(seg[1]) + ("/" + "/".join(seg[2:]) if len(seg) > 2 else "")
    if head == "models":
        return M9B_MODELS + ("/" + "/".join(seg[1:]) if len(seg) > 1 else "")
    if head == "out":
        return M9B_OUT + ("/" + "/".join(seg[1:]) if len(seg) > 1 else "")
    if head in ("base", "local-pack", "kitty-rev", "quant", "merged", "heretic-pareto"):
        return os.path.join(L27B, head) + ("/" + "/".join(seg[1:]) if len(seg) > 1 else "")
    if head in ("scripts", "hf", "tools"):
        return os.path.join(SHARED, head) + ("/" + "/".join(seg[1:]) if len(seg) > 1 else "")
    return path


if __name__ == "__main__":
    for k, v in [("ROOT", ROOT), ("TRAIN", TRAIN), ("L9B", L9B), ("L27B", L27B),
                 ("SHARED", SHARED), ("M9B_MODELS", M9B_MODELS), ("M9B_OUT", M9B_OUT),
                 ("M9B_DATA", M9B_DATA), ("M27B_BASE", M27B_BASE)]:
        print(f"{k:14} {'EXISTS' if os.path.exists(v) else 'MISS  '} {v}")
