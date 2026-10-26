#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t7_pick_val_path.py -- pick_checkpoint 的 --val-data 不许静默消失。

缺陷现象
    val_rows = jsonl(p) if os.path.exists(p) else []
    → 路径打错就静默变成"没有 val 证据"：val_loss=None，排序键 -(None or 99)
      直接把这个维度排到最后，报告里只显示 "-"。
后果
    选优时整个 val 维度静默消失，而报告看起来完全正常（第七个静默错）。
    另：--val-data 只吃一个文件 → forge-val 不参与选优，forge 过拟合看不出来。
正确的断言
    多文件（逗号分隔）会被逐个读取并记录每个文件的行数；
    列出的文件不存在 → 非零退出 + 明确 FATAL。
如果这条 FAIL 说明什么
    --val-data 又退回单文件/静默空集 —— 检查参数解析段。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
SCRIPT = os.path.join(KITTY, "scripts", "pick_checkpoint.py")

fails = []
tmp = tempfile.mkdtemp(prefix="rg-t7-")


def wjsonl(path, n, tag):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"messages": [{"role": "user",
                                              "content": f"{tag} q{i}"},
                                             {"role": "assistant",
                                              "content": f"{tag} a{i}"}]},
                               ensure_ascii=False) + "\n")


try:
    v1 = os.path.join(tmp, "re-subset.val.jsonl")
    v2 = os.path.join(tmp, "forge-subset.val.jsonl")
    wjsonl(v1, 5, "re")
    wjsonl(v2, 3, "forge")
    cand = os.path.join(tmp, "cand")
    os.makedirs(cand)

    def run(val_data):
        return subprocess.run([PY, SCRIPT, "--dry-run", "--candidates", f"c:{cand}",
                               "--val-data", val_data],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    # 1) 单文件
    p = run(v1)
    line = next((l for l in p.stdout.splitlines() if "评测集" in l), "")
    print(f"[single] rc={p.returncode} {line.strip()}")
    if "val=5" not in line:
        fails.append(f"单文件 val 数不对: {line}")

    # 2) 多文件
    p = run(",".join([v1, v2]))
    line = next((l for l in p.stdout.splitlines() if "评测集" in l), "")
    print(f"[multi ] rc={p.returncode} {line.strip()}")
    if "val=8" not in line:
        fails.append(f"多文件 val 数不对（应为 8）: {line}")
    if "forge-subset.val.jsonl" not in line:
        fails.append("报告里看不到 forge-subset 的行数（val_files 没生效）")

    # 3) 打错路径
    p = run(os.path.join(tmp, "nope.val.jsonl"))
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
    print(f"[typo  ] rc={p.returncode} {tail[0]}")
    if p.returncode == 0:
        fails.append("打错路径竟然 rc=0（静默空集）")
    if "FATAL" not in (p.stdout + p.stderr):
        fails.append("打错路径没有 FATAL 提示")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 多文件 val 生效、打错路径显式失败" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
