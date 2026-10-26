#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t14_eval_cat_n.py -- eval_by_cat 的 n_train/n_val 必须进打印行（不许只躺在 json 里）。

缺陷现象
    eval_by_cat() 每个家族会算 n_train / n_val（实际参与 loss 的样本数），
    但 §14.8 的判读只打印 train_drop% / val_drop% / PASS|FAIL|N/A ——
    样本量只写进 eval_by_cat.json，**没有任何下游读者**。
后果
    一条 PASS 可能建立在 1~2 条样本上（max_per_src 截断、某个源只剩一行、val 侧
    只有 1 个文件），而报告看起来和 24 条样本的 PASS 一模一样。
    另一半代价是 N/A：某家族缺可比的 train/val 侧时只打 "N/A"，**没有任何 warn**，
    整条判据静默消失（第 7 例 val_loss 显示 "-" 是同一种形态）。
正确的断言
    ① _fmt_cat_row 的行里带 n(tr/val)=A/B，样本量可见；
    ② 缺 passed_14_8 → 行尾 N/A（不是 PASS，也不是空白）；
    ③ val 侧缺失（val_cache=None）→ n_val 打 "-" 而不是 0，别把"没测"说成"0 条"；
    ④ 结构：smoke 段不再有 `quant = ...` 死变量，且 4bit 不生效时会有 warn
       （旧写法算了个没人读的 quant，打印仍写 dtype=4bit）。
如果这条 FAIL 说明什么
    报告行又退回"只有百分比"的形态，或 smoke 又出现死变量 + 骗人的 dtype 打印。
"""
import ast
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
# 可选 argv[1]：指向另一份 train_partial_lora.py（变异对照用）；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "train_partial_lora.py")
sys.path.insert(0, os.path.dirname(SCRIPT))

fails = []

try:
    tpl = importlib.import_module(os.path.splitext(os.path.basename(SCRIPT))[0])
except Exception as e:
    print(f"\nFAIL: 载入 train_partial_lora 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

if not hasattr(tpl, "_fmt_cat_row"):
    print("\nFAIL: train_partial_lora 缺 _fmt_cat_row()（回归脚本的锚点）")
    sys.exit(1)


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


# ① 正常家族：样本量必须在行里
rec_pass = {"before": {"train_loss": 2.0, "val_loss": 2.2, "n_train": 24, "n_val": 6},
            "after": {"train_loss": 1.4, "val_loss": 1.9, "n_train": 24, "n_val": 6},
            "train_drop_pct": 30.0, "val_drop_pct": 13.64, "passed_14_8": True}
line = tpl._fmt_cat_row("re", rec_pass)
print(f"[line] {line}")
check("行里带 n(tr/val)=24/6", "n(tr/val)=24/6" in line, line)
check("判据仍是 PASS", line.rstrip().endswith("PASS"), line)
check("百分比还在", "train_drop=30.0%" in line and "val_drop=13.64%" in line, line)

# ② 缺 passed_14_8 → N/A（不许静默成 PASS）
rec_na = {"before": {"train_loss": 2.0, "n_train": 3},
          "after": {"train_loss": 1.8, "n_train": 3},
          "train_drop_pct": 10.0}
line_na = tpl._fmt_cat_row("route", rec_na)
print(f"[line] {line_na}")
check("缺 val 侧 → N/A", line_na.rstrip().endswith("N/A"), line_na)
check("N/A 行也看得见样本量", "n(tr/val)=3/-" in line_na, line_na)

# ③ 未过判据 → FAIL，而且和 N/A 不是同一串
rec_fail = dict(rec_pass, passed_14_8=False)
line_fail = tpl._fmt_cat_row("re", rec_fail)
check("未过判据 → FAIL", line_fail.rstrip().endswith("FAIL"), line_fail)
check("FAIL ≠ N/A", "N/A" not in line_fail, line_fail)

# ④ 结构：smoke 段没有死变量 quant，且 4bit 不生效有 warn
src = open(SCRIPT, encoding="utf-8").read()
tree = ast.parse(src)
dead = []
for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
           and n.name == "main"]:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "quant":
                    dead.append(node.lineno)
check("smoke 段没有 quant 死变量", not dead, f"line={dead}")
check("smoke 4bit 有 warn", "smoke 下不生效" in src, "找 '--dtype 4bit 在 smoke 下不生效'")

# ⑤ 结构：main 里必须真的用 _fmt_cat_row() 打这一行
#    只测 helper 不够 —— 把 helper 写对、main 又退回旧 print，报告照样没有样本量
#    （变异对照里就是这样逃掉的，所以这里补一条「有没有被调用」）。
called = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_fmt_cat_row"
             for fn in [x for x in ast.walk(tree) if isinstance(x, ast.FunctionDef)
                        and x.name == "main"]
             for n in ast.walk(fn))
check("main 里调用了 _fmt_cat_row", called, "eval_by_cat 那几行必须走 helper")

print("\nPASS: 样本量进打印行，N/A/FAIL 可分，smoke 不再假装 4bit"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
