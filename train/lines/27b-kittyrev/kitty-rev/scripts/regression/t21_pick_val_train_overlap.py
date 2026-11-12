#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t21_pick_val_train_overlap.py -- val_loss 的可信度必须可见（同问不同答的条数）。

缺陷现象
    pick_checkpoint 的 val_loss 是选优第三键，但报告只给一个数。val 与 train
    存在「同问不同答」时（实测 re-train ∩ re-val = 10 条，action-reverse 模板化
    生成：同一问句套给不同工具，gold 与 train 冲突），val_loss 被抬高，
    读者却会把它当成泛化证据 —— 「val 也降了」这句话失去信息量。
后果
    选优在"背过的题"上比较系数，而报告看起来完全正常（第 6 / 18 例的同族：
    字段有了、判据有了，但"这个数能不能信"没有出口）。
正确的断言
    ① val_train_overlap()：同问 3 条、其中答案不同 2 条 → same_q=3 / diff_a=2；
    ② 无 train（None）→ 返回 None（调用方负责 warn，不许静默当 0）；
    ③ CLI：给了 --train-data 且文件不存在 → FATAL；不给 → 打 [warn] 说明无法核对。
如果这条 FAIL 说明什么
    同问重叠又变成"看不出来的信息"，或缺失被当成 0 处理（S1）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
# 可选 argv[1]：指向另一份 pick_checkpoint.py（变异对照用）；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "pick_checkpoint.py")

fails = []


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


try:
    pc = load_mod(SCRIPT, "pick_ckpt_t21")
except Exception as e:
    print(f"\nFAIL: 载入 pick_checkpoint 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

if not hasattr(pc, "val_train_overlap"):
    print("\nFAIL: pick_checkpoint 缺 val_train_overlap()（回归脚本的锚点）")
    sys.exit(1)


def row(q, a):
    return {"messages": [{"role": "user", "content": q},
                         {"role": "assistant", "content": a}]}


train = [row("Q1", "A1"), row("Q2", "A2"), row("Q3", "A3"), row("Q0", "A0")]
val = [
    row("Q1", "A1"),      # 同问同答
    row("Q2", "A2'"),     # 同问不同答 ①
    row("Q3", "A3'"),     # 同问不同答 ②
    row("Q9", "A9"),      # 全新题
]

ov = pc.val_train_overlap(val, train)
print(f"[info] {ov}")
check("n 正确", ov["n"] == 4, f"n={ov['n']}")
check("同问 3 条", ov["same_q"] == 3, f"same_q={ov['same_q']}")
check("同问不同答 2 条", ov["diff_a"] == 2, f"diff_a={ov['diff_a']}")
check("无 train → None（不是 0）", pc.val_train_overlap(val, []) is None, "空 train")

tmp = tempfile.mkdtemp(prefix="rg-t21-")
try:
    def w(name, rows):
        p = os.path.join(tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p

    re_p, kit_p = w("re.jsonl", val[:1]), w("kit.jsonl", val[:1])
    val_p, tr_p = w("val.jsonl", val), w("train.jsonl", train)

    def run(extra=()):
        cmd = [PY, SCRIPT, "--dry-run", "--candidates", f"c:{tmp}/nope",
               "--re-eval", re_p, "--kitty-eval", kit_p,
               "--val-data", val_p, "--out", os.path.join(tmp, "pick"), *extra]
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120,
                              env=dict(os.environ, PYTHONUTF8="1",
                                       PYTHONIOENCODING="utf-8"))

    p = run(["--train-data", tr_p])
    txt = p.stdout + p.stderr
    line = next((l for l in txt.splitlines() if "与 train 同问" in l), "")
    norm = " ".join(line.split())     # 对齐用的空格会被格式化打断，比较前压平
    print(f"[with   ] rc={p.returncode}  {norm}")
    check("给了 train → 打印同问统计",
          "与 train 同问 3/4" in norm and "答案不同 2" in norm, norm)

    p = run(["--train-data", os.path.join(tmp, "missing.jsonl")])
    txt = p.stdout + p.stderr
    check("train 文件缺失 → FATAL 非零", p.returncode != 0 and "FATAL" in txt,
          txt.strip().splitlines()[-1:])

    p = run()
    txt = p.stdout + p.stderr
    check("没给 train → 有 warn（不许静默）",
          "[warn]" in txt and "同问重叠" in txt,
          [l for l in txt.splitlines() if "[warn]" in l][:1])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 同问重叠可量化、缺失会 warn、错路径 FATAL" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
