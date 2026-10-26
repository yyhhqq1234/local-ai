#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t9_pick_eval_paths.py -- 主判据/回归判据文件缺失必须 FATAL（不许变成 0 题）。

缺陷现象（回归扫描扫出来的第 10 例）
    re_rows  = jsonl(a.re_eval)    if os.path.exists(a.re_eval)    else []
    kit_rows = jsonl(a.kitty_eval) if os.path.exists(a.kitty_eval) else []
    --re-eval 路径打错 → re_rows=[] → 能力主判据（60 题）消失，
    报告照样打印 re_pass=0/0 与 PASS/FAIL 排名，"0 题"看起来只是模型没答对。
后果
    选 checkpoint 时主判据静默消失，只剩 kitty 回归集参与排序。
正确的断言
    --re-eval / --kitty-eval 不存在或 0 行 → 非零退出 + FATAL。
如果这条 FAIL 说明什么
    又退回 `if exists else []` 了 —— 这三处（re/kitty/val）现在必须是同一套加载器。
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
tmp = tempfile.mkdtemp(prefix="rg-t9-")


def wjsonl(path, n):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"messages": [{"role": "user", "content": f"q{i}"}]},
                               ensure_ascii=False) + "\n")


try:
    re_ok = os.path.join(tmp, "re.jsonl")
    kit_ok = os.path.join(tmp, "kit.jsonl")
    val_ok = os.path.join(tmp, "val.jsonl")
    wjsonl(re_ok, 2)
    wjsonl(kit_ok, 2)
    wjsonl(val_ok, 2)
    cand = os.path.join(tmp, "cand")
    os.makedirs(cand)

    def run(**kw):
        cmd = [PY, SCRIPT, "--dry-run", "--candidates", f"c:{cand}",
               "--re-eval", kw.get("re", re_ok),
               "--kitty-eval", kw.get("kit", kit_ok),
               "--val-data", kw.get("val", val_ok)]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    p = run()
    print(f"[正常   ] rc={p.returncode} "
          f"{next((l for l in p.stdout.splitlines() if '评测集' in l), '').strip()}")
    if p.returncode != 0:
        fails.append(f"正常输入失败: {(p.stdout + p.stderr).strip()[-160:]}")

    p = run(re=os.path.join(tmp, "nope.jsonl"))
    print(f"[re缺失 ] rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1]}")
    if p.returncode == 0 or "FATAL" not in (p.stdout + p.stderr):
        fails.append("--re-eval 缺失没有 FATAL")

    p = run(kit=os.path.join(tmp, "nope.jsonl"))
    print(f"[kit缺失] rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1]}")
    if p.returncode == 0 or "FATAL" not in (p.stdout + p.stderr):
        fails.append("--kitty-eval 缺失没有 FATAL")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 三套评测集缺失都会显式失败" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
