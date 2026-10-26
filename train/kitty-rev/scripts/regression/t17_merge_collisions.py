#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t13_merge_collisions.py -- merge-manifest 的 eval_isolation.collisions 不许写死 0。

缺陷现象
    manifest 里 "eval_isolation": {"eval_rows": len(ev), "collisions": 0}
    —— eval_rows 是真的，collisions 是**字面量**，跑多少次都是 0。
后果
    这个字段看着像"隔离冲突计数=0 → 冲突检查跑过了、干净"。第 8 例（--eval 缺失 →
    基线为空 → ABORT 永不触发）就是靠它骗过评审的：当时 eval_rows 也是 0，
    但没人把两个 0 联系起来。字段写死 = 以后把 ABORT 改成"跳过"它也不会变，
    读者永远看不出冲突发生过。
正确的断言
    ① 行为：正常合并 → eval_isolation.eval_rows 等于基线行数、collisions == 0；
    ② 结构：manifest 里 "collisions" 的值必须是**变量**（Name/Subscript 之类），
       不能是 Constant —— 写死字面量是本条缺陷的定义，只能从 AST 上判。
如果这条 FAIL 说明什么
    又有人把计数写成字面量，或者合并流程不再记录隔离基线（回到第 8 例）。
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
# 可选 argv[1]：指向另一份 merge_forge.py（变异对照用）；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "merge_forge.py")

fails = []

# ---- ② 结构：collisions 必须是变量 ---------------------------------------------
src = open(SCRIPT, encoding="utf-8").read()
tree = ast.parse(src)
found = []
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "collisions":
                found.append((node.lineno, type(v).__name__))
if not found:
    fails.append("merge_forge.py 里找不到 \"collisions\" 字段（清单结构变了？）")
else:
    for ln, kind in found:
        print(f"[结构] L{ln} collisions -> {kind}")
        if kind == "Constant":
            fails.append(f"L{ln} collisions 还是字面量（{kind}），不是计数器")

# ---- ① 行为：正常合并时清单字段自洽 -------------------------------------------
tmp = tempfile.mkdtemp(prefix="rg-t13-")
try:
    row = {"messages": [{"role": "user", "content": "q1"},
                        {"role": "assistant", "content": "a1"}]}
    s = os.path.join(tmp, "src.jsonl")
    e = os.path.join(tmp, "eval.jsonl")
    for p in (s, e):
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    out = os.path.join(tmp, "out.jsonl")
    p = subprocess.run([PY, SCRIPT, "--src", s, "--out", out, "--eval", e],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"[行为] rc={p.returncode}")
    if p.returncode != 0:
        fails.append(f"正常合并失败: {(p.stdout + p.stderr).strip()[-200:]}")
    else:
        man = json.load(open(os.path.join(tmp, "merge-manifest.json"), encoding="utf-8"))
        iso = man.get("eval_isolation") or {}
        print(f"[行为] eval_isolation={iso}")
        if iso.get("eval_rows") != 1:
            fails.append(f"eval_rows 不对: {iso.get('eval_rows')}（应为基线 1 行）")
        if iso.get("collisions") != 0:
            fails.append(f"无冲突场景 collisions 应为 0，实得 {iso.get('collisions')}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: collisions 是计数器且与基线自洽" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
