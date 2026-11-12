#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t33_imatrix_gate.py -- gate 2b：imatrix 必须存在、够大、且不早于 bf16 GGUF。

缺陷现象
    `run_after_expand.sh:124` 的 quant 步要求 `$ROOT/imatrix.dat`，但全仓
    `grep -rn llama-imatrix` = 0 命中 —— v3 是手工跑的，v4 一键链会在 ③ 直接 FATAL；
    更坏的一种：有人把 v3 的 imatrix.dat 留在原处，v4 换了模型照旧拿它量化 ——
    命令 rc=0、体积正常、**量化误差静默变大**（与「旧 act-cache 配新 base」同族）。
后果
    要么链路断在一半，要么交付一个"看起来没问题"的更差模型。
正确的断言
    ① 缺文件 → FAIL，且给出 llama-imatrix 的生成命令
    ② 字节 < 1 MiB → FAIL（空/截断产物）
    ③ imatrix 比 bf16.gguf 旧 → FAIL（旧表配新模型）
    ④ 正常（>1 MiB 且更新）→ PASS，rc=0
    ⑤ 缺 .meta.json（calib 出处侧车）→ 只 WARN，不许因此 rc≠0
    ⑥ 带 .meta.json 且四字段齐 → "imatrix 出处完整" PASS
如果这条 FAIL 说明什么
    闸门被绕过/降级，或"旧 imatrix 配新模型"又能静默通过。
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "scripts", "verify_expand.py")
PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def run(root, *extra):
    p = subprocess.run([PY, SCRIPT, "--root", root, "--step", "2b", *extra],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


root = tempfile.mkdtemp(prefix="rg-t33-")
try:
    gguf = os.path.join(root, "bf16.gguf")
    with open(gguf, "wb") as f:
        f.write(b"GGUF" + b"\x00" * 64)
    imx = os.path.join(root, "imatrix.dat")

    # ① 缺文件
    rc, out = run(root)
    check("① 缺 imatrix → rc=1", rc == 1, f"rc={rc}")
    check("① 报错给出生成命令", "llama-imatrix" in out and "-f" in out,
          out.strip().splitlines()[-3:-1])

    # ② 太小
    with open(imx, "wb") as f:
        f.write(b"x" * 10240)
    rc, out = run(root, "--imatrix", imx, "--gguf", gguf)
    check("② 10 KiB → FAIL 字节数", "字节数" in out and "10.0 KiB" in out or "字节数" in out,
          [l for l in out.splitlines() if "字节数" in l][:1])
    check("② 太小 → rc=1", rc == 1, f"rc={rc}")

    # ③ 比 gguf 旧
    with open(imx, "wb") as f:
        f.write(b"y" * (2 << 20))
    old = os.path.getmtime(gguf) - 3600
    os.utime(imx, (old, old))
    rc, out = run(root, "--imatrix", imx, "--gguf", gguf)
    check("③ 旧 imatrix → FAIL 不早于", "不早于 bf16.gguf" in out,
          [l for l in out.splitlines() if "不早于" in l][:1])
    check("③ 旧 imatrix → rc=1", rc == 1, f"rc={rc}")

    # ④ 正常
    now = time.time()
    os.utime(imx, (now, now))
    rc, out = run(root, "--imatrix", imx, "--gguf", gguf)
    check("④ 正常 → rc=0", rc == 0, f"rc={rc}")
    check("④ 正常 → 字节数与先后都 PASS",
          "[PASS] ②b 字节数" in out and "[PASS] ②b imatrix 不早于 bf16.gguf" in out, "")
    check("④ 打印 sha16 指纹（可对账）", "sha16=" in out,
          [l for l in out.splitlines() if "sha16=" in l][:1])
    # ⑤ 缺 meta → 只 WARN
    check("⑤ 缺 .meta.json 只 WARN（不拉红）", "[WARN] ②b 缺" in out and rc == 0, f"rc={rc}")

    # ⑥ 带 meta
    with open(imx + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"calib": "/root/calib.txt", "calib_sha16": "abc123def456",
                   "chunks": 524, "llama_commit": "b1234abc"}, f)
    rc, out = run(root, "--imatrix", imx, "--gguf", gguf)
    check("⑥ 出处齐全 → PASS", "[PASS] ②b imatrix 出处完整" in out and rc == 0,
          [l for l in out.splitlines() if "出处" in l][:1])
    check("⑥ 出处行带 chunks/commit", "chunks=524" in out and "commit=b1234abc" in out, "")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nPASS: imatrix 缺/太小/比模型旧都会被拦，出处侧车只 warn 不绑架判据"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
