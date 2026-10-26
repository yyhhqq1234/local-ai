#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t10_make_re_eval_isolation.py -- 出题脚本的「eval 污染 train」检查不许空转。

缺陷现象（第 11 例）
    val = [...] if os.path.exists(a.val)  else []
    trn = [...] if os.path.exists(a.train) else []
    → 任一路径打错：trn_h 为空 → leaked 恒为空 → 打印「与训练集重叠的素材: 0 条 ✓」，
      而 60 题的 source_hash 全是 None。隔离检查本身失效，报告却显示干净。
后果
    出题脚本从训练集里取材也没人发现 —— 60 题主判据被污染，模型"学会了"但它考的是原题。
正确的断言
    --val / --train 不存在或为空 → 非零退出 + FATAL；
    正常输入 → 写出 60 题；
    真把 val 的一行混进 train → 检查必须报出来并 rc!=0（证明它不是空转）。
如果这条 FAIL 说明什么
    又退回 `if exists else []`，或泄漏检查被放宽成"只报告不失败"。
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
SCRIPT = os.path.join(KITTY, "scripts", "make_re_eval.py")

fails = []
tmp = tempfile.mkdtemp(prefix="rg-t10-")


def wjsonl(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def row(tag):
    return {"messages": [{"role": "user", "content": f"{tag} 问题"},
                         {"role": "assistant", "content": f"{tag} 回答"}],
            "meta": {"cat": "kb-re"}}


try:
    val = os.path.join(tmp, "val.jsonl")
    trn = os.path.join(tmp, "train.jsonl")
    out = os.path.join(tmp, "ev.jsonl")
    wjsonl(val, [row(f"v{i}") for i in range(3)])
    wjsonl(trn, [row(f"t{i}") for i in range(4)])

    def run(**kw):
        cmd = [PY, SCRIPT, "--val", kw.get("val", val), "--train", kw.get("train", trn),
               "--out", kw.get("out", out)]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    # 1) val 缺失
    p = run(val=os.path.join(tmp, "nope.jsonl"))
    print(f"[val缺失 ] rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1][:90]}")
    if p.returncode == 0 or "FATAL" not in (p.stdout + p.stderr):
        fails.append("--val 缺失没有 FATAL")

    # 2) train 缺失（这条才是"隔离检查空转"的入口）
    p = run(train=os.path.join(tmp, "nope.jsonl"))
    print(f"[trn缺失 ] rc={p.returncode} {(p.stdout + p.stderr).strip().splitlines()[-1][:90]}")
    if p.returncode == 0 or "FATAL" not in (p.stdout + p.stderr):
        fails.append("--train 缺失没有 FATAL")

    # 3) 正常出题
    p = run()
    n = sum(1 for l in open(out, encoding="utf-8")) if os.path.exists(out) else 0
    print(f"[正常    ] rc={p.returncode} 题数={n}")
    if p.returncode != 0 or n != 60:
        fails.append(f"正常出题应该 60 题，实得 {n}（rc={p.returncode}）")

    # 4) 真把 val 的一行混进 train → 检查必须抓到
    wjsonl(trn, [row(f"t{i}") for i in range(4)] + [row("v0")])
    p = run()
    txt = p.stdout + p.stderr
    hit = "FATAL" in txt and p.returncode != 0
    print(f"[真污染  ] rc={p.returncode} "
          f"{next((l for l in txt.splitlines() if '重叠' in l), '').strip()}")
    if not hit:
        fails.append("把 val 行混进 train 后检查没报（隔离检查是空转）")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 缺失即 FATAL、真污染必被抓" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
