#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t4_win_drive.py -- --data-mix 的裸 Windows 绝对路径不许丢盘符。

缺陷现象
    parse_mix_item 用 part.split(":", 1) 取源名，于是裸路径 "Z:\\audit\\act" 被拆成
    name="Z"、root="\\audit\\act"。root 是"有根无盘符"路径，Windows 会补当前盘。
后果
    在 D: 上跑就静默读 D:\\audit\\act，在 C: 上跑就读对 —— 同一串参数两种行为，
    而且不报错（目录恰好存在时）。
正确的断言
    裸路径/带权重裸路径的 root 保留盘符；name:path:weight 三段的解析不变；
    name 与目录名不同不影响 MultiCache 构造（name 只是标签）。
如果这条 FAIL 说明什么
    有人又把 name/path 的切分写回 split(":", 1)，或权重解析改成了贪婪匹配。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(KITTY, "scripts"))
import torch  # noqa: E402
from train_partial_lora import parse_mix_item, MultiCache  # noqa: E402

CASES = [
    # (输入, 期望 name, 期望 root, 期望 weight)
    ("re:C:/data/act:3", "re", "C:/data/act", 3.0),
    ("re:C:\\data\\act:3", "re", "C:\\data\\act", 3.0),
    ("re:C:\\data\\act", "re", "C:\\data\\act", 1.0),
    ("Z:\\audit\\act", "act", "Z:\\audit\\act", 1.0),
    ("Z:\\audit\\act:3", "act", "Z:\\audit\\act", 3.0),
    ("D:\\my data\\act route:2.5", "act route", "D:\\my data\\act route", 2.5),
    ("act-re-train", "act-re-train", "act-re-train", 1.0),
    ("act-re-train:0.5", "act-re-train", "act-re-train", 0.5),
]

fails = []
print("=== parse_mix_item ===")
for s, en, er, ew in CASES:
    n, r, w = parse_mix_item(s)
    ok = (n, r, w) == (en, er, ew)
    if not ok:
        fails.append(f"{s!r} → {(n, r, w)}，期望 {(en, er, ew)}")
    drv = (len(r) > 1 and r[1] == ":" and r[0].isalpha())
    tag = "✓" if ok else "✗"
    print(f"[{tag}] {s!r:38s} name={n!r:14s} root={r!r:26s} w={w} 盘符保真={drv}")
    if os.path.isabs(r) or drv:
        if os.path.isabs(r) and not drv and len(s) > 2 and s[1] == ":":
            fails.append(f"{s!r} 解析成无盘符根路径 {r!r}（会落到当前盘）")

print("\n=== name != 目录名（name 只是标签）===")
tmp = tempfile.mkdtemp(prefix="rg-t4-")
try:
    d = os.path.join(tmp, "re-train")
    os.makedirs(d)
    torch.save({"hidden": torch.zeros(1, 4, 2, dtype=torch.bfloat16),
                "labels": torch.zeros(1, 4, dtype=torch.long),
                "attn": torch.ones(1, 4, dtype=torch.long)},
               os.path.join(d, "0.pt"))
    try:
        c = MultiCache([("forge", d, 4.0)], 512)
        print(f"[✓] name='forge' 指向目录 re-train → 构造成功 names={c.names}")
    except SystemExit as e:
        fails.append(f"name≠目录被误杀: {e}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 盘符保真、name/path 解耦" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
