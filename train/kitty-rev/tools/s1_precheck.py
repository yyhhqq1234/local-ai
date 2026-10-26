#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s1_precheck.py —— S1 训练启动前的 8 项预检（云端跑，G1 之后、训练之前）

为什么需要：S1 是 3-4 小时，任何一项不满足都会在启动后几十秒到几分钟内失败，
但失败信息往往指向"训练脚本报错"而不是"前置条件缺失"。这个脚本把前置条件
全部显式化，让 FAIL 只可能出在训练逻辑本身。

判据（任一 FAIL 就不许起训练）：
  1 base 18 片齐全且字节与 shards.txt 逐个等号
  2 index.json 张量数 == 1199
  3 v5-mix/train.jsonl 行数 ≥ 1000 且每行可解析
  4 GPU 空闲（已被占用的显存 < 2 GiB）
  5 磁盘剩余 ≥ 60 G（训练要写 adapter + checkpoint）
  6 torch / transformers / peft / bitsandbytes 可导入且版本打印
  7 train_kitty.py 可 import（语法与依赖）
  8 显存总量 ≥ 22 GiB（27B 4bit + LoRA + ctx2048 的下限）

用法（云端）：
  /root/miniconda3/bin/python tools/s1_precheck.py
  echo $?   # 0=全过，1=有 FAIL
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

R = Path("/root/autodl-tmp/kitty-rev")
BASE = R / "base/Huihui"
SHARDS = R / "tmp/_base/shards.txt"
MIX = R / "data/intent3/v5-mix/train.jsonl"
TRAINER = R / "scripts/train_kitty.py"

FAILS: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def bad(msg: str) -> None:
    print(f"  ✗ {msg}")
    FAILS.append(msg)


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return 1, f"{type(e).__name__}: {e}"


print("=== 1 base 18 片逐个等号 ===")
if not SHARDS.exists():
    bad(f"缺 {SHARDS}")
else:
    want = {}
    for line in SHARDS.read_text().replace("\r", "").splitlines():
        if line.strip():
            name, size = line.split()
            want[name] = int(size)
    missing, mismatch = [], []
    for name, size in want.items():
        p = BASE / name
        if not p.exists():
            missing.append(name)
        elif p.stat().st_size != size:
            mismatch.append(f"{name}: {p.stat().st_size} != {size}")
    if missing:
        bad(f"缺 {len(missing)} 片: {missing[:3]}...")
    elif mismatch:
        bad(f"{len(mismatch)} 片字节不符: {mismatch[:3]}")
    else:
        total = sum(want.values())
        ok(f"{len(want)} 片全部 EQ，合计 {total:,} B")

print("=== 2 index.json 张量数 ===")
idx = BASE / "model.safetensors.index.json"
if not idx.exists():
    bad("缺 model.safetensors.index.json（merge 后别忘了补拷）")
else:
    try:
        n = len(json.loads(idx.read_text())["weight_map"])
        if n == 1199:
            ok(f"weight_map = {n}")
        else:
            bad(f"weight_map = {n}，期望 1199")
    except Exception as e:  # noqa: BLE001
        bad(f"index 解析失败: {e}")

print("=== 3 v5-mix 训练集 ===")
if not MIX.exists():
    bad(f"缺 {MIX}")
else:
    n = bad_lines = 0
    for line in MIX.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        try:
            d = json.loads(line)
            if not isinstance(d.get("messages"), list) or len(d["messages"]) < 2:
                bad_lines += 1
        except Exception:  # noqa: BLE001
            bad_lines += 1
    if n < 1000:
        bad(f"仅 {n} 行（期望 ≥1000）")
    elif bad_lines:
        bad(f"{bad_lines} 行格式不合（缺 messages 或 <2 轮）")
    else:
        ok(f"{n} 行，格式全合规")

print("=== 4 GPU 空闲 ===")
rc, out = run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"])
if rc != 0:
    bad(f"nvidia-smi 失败: {out[:120]}")
else:
    try:
        used, total = [int(x) for x in out.splitlines()[0].split(",")]
        if used > 2048:
            bad(f"显存已被占 {used} MiB（期望 <2048）")
        else:
            ok(f"已用 {used} MiB / 总 {total} MiB")
        if total < 22000:
            bad(f"显存总量 {total} MiB < 22000（27B 4bit 下限）")
    except Exception as e:  # noqa: BLE001
        bad(f"解析 nvidia-smi 失败: {e}")

print("=== 5 磁盘剩余 ===")
st = os.statvfs("/root/autodl-tmp")
free_g = st.f_bavail * st.f_frsize / 1e9
if free_g < 60:
    bad(f"剩余 {free_g:.1f} G < 60 G")
else:
    ok(f"剩余 {free_g:.1f} G")

print("=== 6 训练依赖版本 ===")
code = (
    "import torch,transformers,peft;"
    "import bitsandbytes as bnb;"
    "print('torch',torch.__version__);"
    "print('transformers',transformers.__version__);"
    "print('peft',peft.__version__);"
    "print('bnb',bnb.__version__);"
    "print('cuda',torch.cuda.is_available())"
)
rc, out = run([sys.executable, "-c", code])
if rc != 0:
    bad(f"依赖导入失败: {out[:200]}")
else:
    for line in out.splitlines():
        print(f"    {line}")
    if "cuda True" not in out:
        bad("torch.cuda.is_available() 不是 True")
    else:
        ok("依赖齐 + CUDA 可用")

print("=== 7 train_kitty.py 可导入 ===")
if not TRAINER.exists():
    bad(f"缺 {TRAINER}")
else:
    rc, out = run([sys.executable, "-c", f"import ast;ast.parse(open({str(TRAINER)!r}).read());print('AST_OK')"])
    if rc == 0 and "AST_OK" in out:
        ok(f"{TRAINER.name} AST 解析通过（{TRAINER.stat().st_size:,} B）")
    else:
        bad(f"AST 解析失败: {out[:200]}")

print()
if FAILS:
    print(f"[VERDICT] FAIL —— {len(FAILS)} 项不满足，**不许起训练**")
    for f in FAILS:
        print(f"  · {f}")
    sys.exit(1)
print("[VERDICT] PASS —— 8 项全过，可以起 S1 训练")
sys.exit(0)
