#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t2_mix_foreign_pt.py -- act-cache 目录混入异源 .pt 必须 FATAL。

缺陷现象
    MultiCache 用 sorted(glob("*.pt")) 取文件，**不校验内容**。别人拷进来的 .pt
    会按文件名排进序列，于是 A 样本的 hidden 配 B 样本的 labels。
后果
    不报错，训练在垃圾标签上跑完，loss 可能还"正常下降"（模型学会了错的对齐）。
正确的断言
    目录里的 .pt 数与 manifest.count 不一致 → SystemExit；
    文件名集合与 manifest.samples 不一致 → SystemExit；
    两者一致 → 正常构造。
如果这条 FAIL 说明什么
    manifest 守卫被绕过（比如新代码用了 glob 但没走 __init__，或把检查改成 warn）。
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(KITTY, "scripts"))
import torch  # noqa: E402
from train_partial_lora import MultiCache  # noqa: E402


def make(dirpath, n, manifest_count=None, manifest_names=None, skill_file=False):
    os.makedirs(dirpath, exist_ok=True)
    for i in range(n):
        torch.save({"hidden": torch.zeros(1, 4, 2, dtype=torch.bfloat16),
                    "labels": torch.zeros(1, 4, dtype=torch.long),
                    "attn": torch.ones(1, 4, dtype=torch.long)},
                   os.path.join(dirpath, f"{i}.pt"))
    names = manifest_names if manifest_names is not None else [f"{i}.pt" for i in range(n)]
    if manifest_count is not None or manifest_names is not None:
        json.dump({"count": manifest_count if manifest_count is not None else n,
                   "samples": names},
                  open(os.path.join(dirpath, "manifest.json"), "w", encoding="utf-8"))


fails = []
base = tempfile.mkdtemp(prefix="rg-t2-")
try:
    # 1) 一致 → 通过
    d_ok = os.path.join(base, "ok")
    make(d_ok, 3)
    try:
        c = MultiCache([("ok", d_ok, 1.0)], 512)
        print(f"[ok   ] 3 个 .pt + count=3 → 构造成功（{len(c)} 样本）")
    except SystemExit as e:
        fails.append(f"一致目录被误杀: {e}")

    # 2) 数量不符（异源 .pt 被拷进来）→ 必须 FATAL
    d_bad = os.path.join(base, "bad")
    make(d_bad, 3, manifest_count=4, manifest_names=["0.pt", "1.pt", "2.pt", "3.pt"])
    try:
        MultiCache([("bad", d_bad, 1.0)], 512)
        fails.append("数量不符没有 FATAL")
        print("[FAIL] 3 个 .pt / count=4 竟然构造成功")
    except SystemExit as e:
        print(f"[bad  ] 数量不符 → FATAL ✓  {str(e).splitlines()[0]}")

    # 3) 集合不符（少了文件）→ 必须 FATAL
    d_miss = os.path.join(base, "miss")
    make(d_miss, 2, manifest_count=2, manifest_names=["0.pt", "1.pt", "9.pt"])
    try:
        MultiCache([("miss", d_miss, 1.0)], 512)
        fails.append("集合不符没有 FATAL")
        print("[FAIL] 缺文件竟然构造成功")
    except SystemExit as e:
        print(f"[miss ] 集合不符 → FATAL ✓  {str(e).splitlines()[0]}")
finally:
    shutil.rmtree(base, ignore_errors=True)

print("\nPASS: 异源/缺失 .pt 都会被拒" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
