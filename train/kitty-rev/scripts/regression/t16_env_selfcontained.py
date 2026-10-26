#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t16_env_selfcontained.py -- run_all.py 的编码守卫必须自包含（防「假失败」）。

缺陷现象（第 14 例·假失败，2026-10-21 本机实测）
    控制台默认 GBK(cp936)。run_all 用 subprocess 跑 t1..t12 并捕获输出，
    子进程里任何非 GBK 字符的 print 都抛 UnicodeEncodeError → 子进程 rc=1
    → 汇总表把 PASS 打成 FAIL；汇总行自己又崩在同一异常上 → 输出变成
    「2 条假 FAIL + traceback」。实测 t10/t11 假红，代码本身零缺陷。

后果
    环境健康的基线读数不可信。以后每个接手的人第一步都跑 run_all，看到假红
    就去查 t10/t11 的代码（白查），而不是查环境。

正确的断言（四段式）
    ① 正向：显式 utf-8（PYTHONIOENCODING=utf-8 + PYTHONUTF8=1，即 run_all 的
       CHILD_ENV 口径）跑一个打印 ✓ 的 mini 子进程 → rc=0 且输出真的是 ✓。
    ② 基线：**裸**环境（两个变量都不设）跑同一个 mini 子进程。
       本机实测（3.13.9 / utf8_mode=0 / locale cp936）**照样炸** —— 所以
       「假失败」根本不需要谁去显式设 gbk，继承控制台默认编码就够了。
       这条只作基线记录：若某天 Python 默认 UTF-8 了，它变绿也不代表守卫可以删。
    ③ 检出：强制 PYTHONIOENCODING=gbk 跑同一个 → rc!=0 且 stderr 出现
       UnicodeEncodeError。← 这段证明「本测试能抓到假失败」，不是永远绿的装饰。
    ④ 覆盖：同样在 gbk 父环境下 import run_all，用它的 CHILD_ENV 再跑
       同一个 mini 子进程 → rc=0 且是 ✓，并断言 CHILD_ENV 里两个键被
       **覆盖**成 utf-8/1（setdefault 在这里不够：显式 gbk 会被沉默接受）。

如果这条 FAIL 说明什么
    ④ 挂了 → run_all 的 CHILD_ENV 退回 dict(os.environ) / setdefault，
            显式 gbk 会漏进子进程，假失败复发。
    ③ 挂了 → 说明这台机器的 Python 已经默认 UTF-8（前提失效，请改断言而不是删测试）。
    ① 挂了 → 守卫口径本身不对（utf-8 都编不出 ✓），比假失败更严重。
"""
import os
import subprocess
import sys

# 本脚本自己也要自包含：它在打印 ✓，GBK 控制台直接跑会崩在同一个异常上
# （run_all 会给子进程传 utf-8，但"单跑 t13"这条路径没人替它设）。
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_ALL = os.path.join(HERE, "run_all.py")
PY = sys.executable
MARK = "\u2713"                      # ✓：GBK 编码不了，utf-8 能

# 子进程只做一件事：打印 ✓（不读文件、不加载模型）
MINI = f"print('{MARK}')"

CLEAN = {k: v for k, v in os.environ.items()
         if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
UTF8 = dict(CLEAN, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")   # = run_all 的 CHILD_ENV 口径
GBK = dict(CLEAN, PYTHONIOENCODING="gbk", PYTHONUTF8="0")

fails = []


def run_mini(env, label):
    p = subprocess.run([PY, "-c", MINI], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, env=env)
    out, err = (p.stdout or "").strip(), (p.stderr or "")
    print(f"[{label}] rc={p.returncode} stdout={out!r} "
          f"{'UnicodeEncodeError' if 'UnicodeEncodeError' in err else ''}")
    return p.returncode, out, err


# ---------------- ① 正向：显式 utf-8（= run_all 的 CHILD_ENV 口径） ----------------
print("=== ① 显式 utf-8（守卫口径）===")
rc, out, err = run_mini(UTF8, "utf8")
if rc != 0 or out != MARK:
    fails.append(f"① utf-8 口径没拿到 ✓: rc={rc} out={out!r}")
    print(f"[✗] 期望 rc=0 且 stdout={MARK!r}")
else:
    print(f"[✓] rc=0，stdout 是 {MARK!r}")

# ---------------- ② 基线：裸环境也炸（假失败不需要谁去设 gbk） ----------------
print("\n=== ② 裸环境基线 ===")
rc, out, err = run_mini(CLEAN, "bare")
if rc != 0:
    print(f"[✓] 裸环境同样 rc={rc}（cp936 继承即炸）—— 假失败的来源，与是否显式设 gbk 无关")
else:
    print(f"[·] 裸环境 rc=0（本机 Python 已默认 UTF-8？）—— 基线变化，守卫仍需保留")

# ---------------- ③ 检出：显式 gbk 必须炸（证明本测试能抓假失败） ----------------
print("\n=== ③ 显式 gbk（检出能力）===")
rc, out, err = run_mini(GBK, "gbk")
if rc == 0:
    fails.append("③ gbk 下没炸 —— 测试前提失效（本机默认编码可能已改），"
                 "请改断言而不是删这条")
    print("[✗] gbk 下居然成功了，本测试抓不到假失败")
else:
    hit = "UnicodeEncodeError" in err
    print(f"[{'✓' if hit else '✗'}] rc={rc} 且 {('stderr 有 UnicodeEncodeError' if hit else 'stderr 无 UnicodeEncodeError')}")
    if not hit:
        fails.append(f"③ rc={rc} 但不是 UnicodeEncodeError: {err.strip().splitlines()[-1:] }")

# ---------------- ④ 覆盖：run_all.CHILD_ENV 必须压回 utf-8 ----------------
print("\n=== ④ run_all 的 CHILD_ENV（gbk 父环境下）===")
probe = (
    "import importlib.util, os, subprocess, sys\n"
    f"spec = importlib.util.spec_from_file_location('run_all_probe', {RUN_ALL!r})\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "sys.modules['run_all_probe'] = m\n"
    "spec.loader.exec_module(m)\n"          # 模块级守卫在这里执行（含 reconfigure）
    "print('CHILD_ENV', m.CHILD_ENV['PYTHONIOENCODING'], m.CHILD_ENV['PYTHONUTF8'])\n"
    f"p = subprocess.run([sys.executable, '-c', {MINI!r}], capture_output=True,\n"
    "                   text=True, encoding='utf-8', errors='replace', env=m.CHILD_ENV)\n"
    "print('MINI', p.returncode, (p.stdout or '').strip())\n"
)
p = subprocess.run([PY, "-c", probe], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=120, env=GBK)
txt = (p.stdout or "") + (p.stderr or "")
child_line = next((l for l in txt.splitlines() if l.startswith("CHILD_ENV")), "")
mini_line = next((l for l in txt.splitlines() if l.startswith("MINI")), "")
print(f"[{'✓' if child_line == 'CHILD_ENV utf-8 1' else '✗'}] {child_line or '(没有 CHILD_ENV 行)'}")
print(f"[{'✓' if mini_line == f'MINI 0 {MARK}' else '✗'}] {mini_line or '(没有 MINI 行)'}")
if child_line != "CHILD_ENV utf-8 1":
    fails.append(f"④ CHILD_ENV 没把 gbk 覆盖掉: {child_line!r}（setdefault 不够，必须覆盖）")
if mini_line != f"MINI 0 {MARK}":
    fails.append(f"④ 用 CHILD_ENV 跑 mini 子进程失败: {mini_line!r}")
if p.returncode != 0:
    fails.append(f"④ 探针进程 rc={p.returncode}: {txt.strip().splitlines()[-1:]}")
else:
    print("[✓] 探针进程 rc=0（gbk 父环境下 import run_all 没崩，reconfigure 守卫生效）")

# ---------------- ④ 静态：自证行还在（没有它，日后又分不清真假 FAIL） ----------------
src = open(RUN_ALL, encoding="utf-8").read()
if "[env]" in src and "reconfigure" in src and "**_REQUIRED" in src:
    print("\n[✓] 静态检查：[env] 自证行 + reconfigure + CHILD_ENV 覆盖三件都在")
else:
    fails.append("④ run_all.py 缺 [env] 自证行 / reconfigure / CHILD_ENV 覆盖 之一")
    print("\n[✗] 静态检查缺件")

print("\nPASS: 编码守卫自包含（utf-8 正向、gbk 必炸、CHILD_ENV 覆盖生效）"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
