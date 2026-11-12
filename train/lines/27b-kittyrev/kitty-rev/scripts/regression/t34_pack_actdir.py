#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t34_pack_actdir.py -- gate 7：pack 里必须有 act-cache 目录名契约。

缺陷现象
    v4 的 act-cache 目录叫 `act-cache-v4`，而本地 `deploy/local_train.ps1`
    硬编码找 `act-cache`。tar 里"看得见一堆 .pt"，但本地一键训练解包后
    在"缺 act-cache"处死掉 —— 而 pack 那一步 exit 0、条目数也对。
后果
    交付物在云端全绿，到 5070 Ti 上才知道跑不起来（回传 25 G 之后）。
正确的断言
    ① tar 里有 `act-cache/` → PASS
    ② 只有 `act-cache-v4/` 且没有契约文件 → FAIL，且报错点出 local_train.ps1
    ③ 有 `.act-cache-dir-name=act-cache-v4` 且该目录在场 → PASS（契约逃生口）
    ④ 契约声明的目录在 tar 里不存在 → FAIL（声明与内容分家）
如果这条 FAIL 说明什么
    gate 7 不再校验目录名契约，本地一键训练又会在解包后才炸。
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

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


def make_tar(path, act_name, n_pt=3, contract=None):
    """造一个最小 pack：<act_name>/<i>.pt × n、head、index、（可选）契约文件。"""
    with tarfile.open(path, "w") as tf:
        if act_name:
            ti = tarfile.TarInfo(act_name)
            ti.type = tarfile.DIRTYPE
            tf.addfile(ti)
            for i in range(n_pt):
                ti = tarfile.TarInfo(f"{act_name}/{i}.pt")
                ti.size = 0
                tf.addfile(ti)
            for nm in ("head.safetensors", "index.json"):
                ti = tarfile.TarInfo(f"{act_name}/{nm}")
                ti.size = 0
                tf.addfile(ti)
        if contract is not None:
            blob = contract.encode("utf-8")
            ti = tarfile.TarInfo(".act-cache-dir-name")
            ti.size = len(blob)
            tf.addfile(ti, io.BytesIO(blob))
    return path


def run(root, pack):
    # 用小期望值把 fixture 缩到 3 个 .pt（同时验证 --set 通路）
    p = subprocess.run([PY, SCRIPT, "--root", root, "--step", "7", "--pack", pack,
                        "--set", "pack_pt=3", "--set", "pack_layers=0",
                        "--set", "pack_dirs=1"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONUTF8="1",
                                                  PYTHONIOENCODING="utf-8"), timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


root = tempfile.mkdtemp(prefix="rg-t34-")
try:
    # ① 标准名 act-cache/
    p1 = make_tar(os.path.join(root, "a.tar"), "act-cache")
    rc, out = run(root, p1)
    check("① tar 里有 act-cache/ → rc=0", rc == 0, f"rc={rc}")
    check("① 打印 act-cache 目录在场", "[PASS] ⑦ act-cache 目录在场" in out,
          [l for l in out.splitlines() if "act-cache 目录在场" in l][:1])

    # ② 只有 act-cache-v4/，无契约 → FAIL
    p2 = make_tar(os.path.join(root, "b.tar"), "act-cache-v4")
    rc, out = run(root, p2)
    check("② 无契约 → rc=1", rc == 1, f"rc={rc}")
    check("② 报错点出 local_train.ps1", "local_train.ps1" in out,
          [l for l in out.splitlines() if "act-cache 目录在场" in l][:1])
    check("② 报错列出顶层目录（可诊断）", "act-cache-v4" in out, "")

    # ③ 契约指向存在的目录 → PASS
    p3 = make_tar(os.path.join(root, "c.tar"), "act-cache-v4", contract="act-cache-v4")
    rc, out = run(root, p3)
    check("③ 契约名在场 → rc=0", rc == 0, f"rc={rc}")
    check("③ 打印按契约名找到目录", "act-cache 目录在场（按契约名）" in out,
          [l for l in out.splitlines() if "按契约名" in l][:1])

    # ④ 契约指向不存在的目录 → FAIL
    p4 = make_tar(os.path.join(root, "d.tar"), "act-cache-v4", contract="act-cache-vX")
    rc, out = run(root, p4)
    check("④ 契约与内容分家 → rc=1", rc == 1, f"rc={rc}")
    check("④ 报错说明声明 vs 实际", "声明=" in out,
          [l for l in out.splitlines() if "声明=" in l][:1])

    # ⑤ 两套都在（act-cache/ + 契约写 v4）→ 允许但必须 warn
    p5 = make_tar(os.path.join(root, "e.tar"), "act-cache", contract="act-cache-v4")
    rc, out = run(root, p5)
    check("⑤ 两套并存 → rc=0 但 warn", rc == 0 and "[WARN]" in out, f"rc={rc}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nPASS: act-cache 目录名有契约（在场/PASS、缺失/FAIL、分家/FAIL），本地不会解包后才炸"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
