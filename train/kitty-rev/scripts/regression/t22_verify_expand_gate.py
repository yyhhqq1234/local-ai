#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t22_verify_expand_gate.py -- 七步产物闸门自身必须可证伪（verify_expand --selftest）。

缺陷现象（不是脚本 bug，是**闸门可能没牙**）
    `set -e` 只保证"命令失败就停"，保证不了"命令成功但产物错"。
    verify_expand.py 的每条判据都必须是**可红的**：喂它一个错误产物要 FAIL，
    否则它只是一堆漂亮的 PASS 输出（第 20 例同族：判据存在 ≠ 判据生效）。
后果
    七步跑完、闸门全绿、扩容包其实是错的（adapter 没合并 / 没真量化 / 全落 rest），
    等到训练或推理阶段才发现，51 G 的产物全部重来。
正确的断言
    `verify_expand.py --selftest` rc=0，且输出 "SELFTEST PASS"；
    这条同时守住：① 闸门脚本能 import（前向引用/语法）② 每条判据在错样本上都会红。
如果这条 FAIL 说明什么
    闸门失效（某条判据不再能红）或闸门脚本本身跑不起来 —— 先看 selftest 里
    哪一条 `↑ ... 被抓：NO` 或 `误杀`。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
SCRIPT = os.path.join(KITTY, "scripts", "verify_expand.py")

fails = []
if not os.path.isfile(SCRIPT):
    print(f"\nFAIL: 缺 {SCRIPT}")
    sys.exit(1)

p = subprocess.run([PY, SCRIPT, "--selftest"], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=180,
                   env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
txt = (p.stdout or "") + (p.stderr or "")
print("\n".join(l for l in txt.splitlines()
                if ("被抓" in l or "SELFTEST" in l or "误杀" in l)))

if p.returncode != 0:
    fails.append(f"selftest rc={p.returncode}")
if "SELFTEST PASS" not in txt:
    fails.append("没有 SELFTEST PASS")
for must in ("未合并的样本被抓", "tensor 数不符被抓", "未量化（F16）被抓", "全落 rest 被抓"):
    line = next((l for l in txt.splitlines() if must in l), "")
    if "YES" not in line:
        fails.append(f"判据不再可红: {must}（{line.strip()[:60]}）")

print("\nPASS: 七步闸门每条判据都能红（selftest 通过）" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
