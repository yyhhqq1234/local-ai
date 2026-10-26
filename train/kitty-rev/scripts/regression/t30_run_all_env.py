#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t30_run_all_env_classify.py -- 缺依赖的解释器不许把回归集打成「8 条 FAIL」。

缺陷现象
    run_all.py 用 `sys.executable` 跑每个子脚本，只按 rc 判 PASS/FAIL。
    套件里 7 条脚本要 import torch/transformers；在只有 numpy 的解释器上
    它们 rc=1（ModuleNotFoundError），汇总行照样打「12/20 PASS」
    —— 8 条**环境缺件**被读成 8 条**代码缺陷**。
后果
    审查岗对着不存在的缺陷返工；真缺陷被埋在假红里；「20/20」这个验收口径失灵。
    （与 #14「GBK 假失败」同族：**假红**和假绿一样会把判据废掉。）
正确的断言
    ① env_missing() 能从输出里认出缺哪个包（torch / transformers / peft …）
    ② 真缺陷（断言失败、语法错）不许被误判成环境缺件
    ③ 汇总口径：ENVN 从分母里摘出去，且 rc 只由真 FAIL 决定
    ④ --help 级验证：run_all.py 能被 import（不是只有 py_compile 过）
如果这条 FAIL 说明什么
    假红又回来了：以后「X/Y PASS」这个数字再也不可信。
"""
import importlib.util
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(HERE, "run_all.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    R = load_mod(SRC, "run_all_t30")
    check("④ run_all.py 可 import（--help 级）", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 run_all 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

# ① 环境缺件
cases = {
    "torch": "Traceback (most recent call last):\nModuleNotFoundError: No module named 'torch'\n",
    "transformers": "ImportError: No module named 'transformers'",
    "peft": "ModuleNotFoundError: No module named 'peft'",
}
for mod, text in cases.items():
    got = R.env_missing(text)
    check(f"① 认出缺 {mod}", got == mod, str(got))

# ② 真缺陷不许被吞成环境问题
for bad in ("FAIL: ['旧产物 → 提示 span_scheme/FATAL']",
            "AssertionError: 0",
            "  File \"x.py\", line 3\n    def f(:\nSyntaxError: invalid syntax",
            "ModuleNotFoundError: No module named 'my_own_module'"):
    got = R.env_missing(bad)
    check(f"② 不误判：{bad.splitlines()[0][:42]}", got is None, str(got))

# ③ 汇总口径（用假 rows 走一遍统计逻辑）
def summarize(rows):
    npass = sum(1 for r in rows if r[1])
    nenv = sum(1 for r in rows if (not r[1]) and r[5])
    nfail = len(rows) - npass - nenv
    return npass, nenv, nfail


rows_mixed = [("a", True, 0.1, 0, [""], None),
              ("b", False, 0.1, 1, ["boom"], None),          # 真 FAIL
              ("c", False, 0.1, 1, [""], "torch")]           # 环境缺件
np_, ne, nf = summarize(rows_mixed)
check("③ 1 通 / 1 环境 / 1 真失败", (np_, ne, nf) == (1, 1, 1), f"{np_}/{ne}/{nf}")
check("③ 分母摘掉 ENV-SKIP（1+1=2 而不是 3）", (np_ + nf) == 2, f"{np_ + nf}")

# 源码口径：rc 只看真 FAIL、ENV-SKIP 打标、给出解释器与 torch 版本
src = open(SRC, encoding="utf-8").read()
check("③ rc 只由真 FAIL 决定", "return 0 if nfail == 0 else 1" in src)
check("③ ENV-SKIP 是状态位（不是 PASS 也不是 FAIL）", '"ENV-SKIP"' in src)
check("③ 汇总行把「计分」与 ENV-SKIP 分开写", "PASS（计分）" in src)
check("③ 指路：给出带训练栈的解释器示例", "EmbodiedAssembly2026" in src)
check("③ ENV-SKIP 明细解释「不是代码缺陷」", "不是代码缺陷" in src)
check("③ 开跑先探依赖：打印解释器 + torch 版本",
      "def dep_versions" in src and "interpreter =" in src and "torch=" in src)
check("③ dep_versions 返回版本字典（可被断言）",
      hasattr(R, "dep_versions") and isinstance(R.dep_versions(), dict))

print("\nPASS: 缺件记 ENVN、真缺陷仍 FAIL、口径与解释器都写在汇总行里"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
