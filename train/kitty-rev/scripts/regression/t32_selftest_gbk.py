#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t32_selftest_gbk.py -- 自检脚本在 GBK 控制台上不许"假崩"。

缺陷现象
    verify_expand.py / eval_re_extended.py 的 --selftest 会打印 `≥` / `✓`。
    云端是 UTF-8 无碍；Windows 控制台是 cp936(GBK)，且没设 PYTHONIOENCODING 时
    直接 `python xxx.py --selftest` 抛：
        UnicodeEncodeError: 'gbk' codec can't encode character '\\u2287'
    —— traceback 看起来像"自检挂了/代码坏了"，实际只是编码。
后果
    runbook 让 train-watch 手动跑 selftest（G3/G6），他会在第一屏看到"崩了"，
    于是跳过自检或去改代码；这与 #14「GBK 假失败」同族，只是换了个入口。
正确的断言
    ① 两个脚本源码里都有 stdout/stderr 重绑定（自保，不靠调用者记得设环境变量）
    ② 在**强制 GBK**（PYTHONIOENCODING 清空 + PYTHONUTF8=0）下跑 --selftest → rc=0
    ③ 子进程环境确实没有 PYTHONIOENCODING（不然这条断言就是空跑）
如果这条 FAIL 说明什么
    自保代码被删，或又有人在自检输出里加了只能在 UTF-8 下打印的字符。
"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
TARGETS = [os.path.join(KITTY, "scripts", "verify_expand.py"),
           os.path.join(KITTY, "scripts", "eval_re_extended.py"),
           os.path.join(KITTY, "scripts", "refusal_probe.py")]
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


# ③ 构造"强制 GBK"环境：清掉 PYTHONIOENCODING，关掉 UTF-8 模式
env = dict(os.environ)
env.pop("PYTHONIOENCODING", None)
env["PYTHONUTF8"] = "0"
check("③ 子进程环境里确实没有 PYTHONIOENCODING（否则断言空跑）",
      "PYTHONIOENCODING" not in env) 

for p in TARGETS:
    base = os.path.basename(p)
    src = open(p, encoding="utf-8").read()
    # ① 自保代码在位
    check(f"① {base} 有 stdout 重绑定", "sys.stdout.reconfigure" in src)
    check(f"① {base} 有 stderr 重绑定", "sys.stderr.reconfigure" in src)
    # ② 真跑一遍（GBK 环境）
    r = subprocess.run([PY, p, "--selftest"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    check(f"② {base} --selftest 在 GBK 环境 rc=0", r.returncode == 0, f"rc={r.returncode}")
    check(f"② {base} 没有 UnicodeEncodeError", "UnicodeEncodeError" not in out,
          out.strip().splitlines()[-1][:80] if out.strip() else "(无输出)")
    check(f"② {base} 打出自己的结论行",
          ("SELFTEST" in out) or ("selftest" in out.lower()), out.strip().splitlines()[-1:])

print("\nPASS: 两个自检脚本在 GBK 控制台下不再假崩（自保代码在位且实测 rc=0）"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
