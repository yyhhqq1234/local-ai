#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t5_dup_source.py -- 同名源必须 FATAL（不许静默吞掉第二个目录）。

缺陷现象
    MultiCache.of(name) 只 yield 第一个同名 spec，summary() 又是以 name 为键的 dict。
    于是 --data-mix "re:a,re:b" 里 b 目录：训练照抽（取样池包含它），
    验证/报告完全看不到它。
后果
    你以为在验证 re 这一类，实际验证的只有 a；权重配比表也少一半。
正确的断言
    构造同名源 → SystemExit（消息里带"源名重复"）；不同名照常构造。
如果这条 FAIL 说明什么
    重名检查被删了，或 of()/summary() 改成了按 root 索引（那样就不用报错，但请改断言）。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(KITTY, "scripts"))
import torch  # noqa: E402
from train_partial_lora import MultiCache  # noqa: E402


def mk(dirpath):
    os.makedirs(dirpath, exist_ok=True)
    torch.save({"hidden": torch.zeros(1, 4, 2, dtype=torch.bfloat16),
                "labels": torch.zeros(1, 4, dtype=torch.long),
                "attn": torch.ones(1, 4, dtype=torch.long)},
               os.path.join(dirpath, "0.pt"))


fails = []
tmp = tempfile.mkdtemp(prefix="rg-t5-")
try:
    a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
    mk(a)
    mk(b)

    try:
        MultiCache([("re", a, 1.0), ("re", b, 2.0)], 512)
        fails.append("同名源没有 FATAL")
        print("[FAIL] --data-mix 're:a,re:b' 竟然构造成功（第二个目录会被静默吞掉）")
    except SystemExit as e:
        msg = str(e)
        ok = "源名重复" in msg
        print(f"[{'✓' if ok else '✗'}] 同名源 → FATAL：{msg.splitlines()[0]}")
        if not ok:
            fails.append(f"FATAL 消息没点明重名: {msg[:80]}")

    try:
        c = MultiCache([("re", a, 1.0), ("route", b, 2.0)], 512)
        print(f"[✓] 不同名 → 构造成功 names={c.names} summary={list(c.summary())}")
    except SystemExit as e:
        fails.append(f"不同名被误杀: {e}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 重名源被拒、不同名不受影响" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
