import io, os
p = "eval/eval_kitty.py"
s = open(p, encoding="utf-8").read()
if "DEPRECATED" not in s[:400]:
    hdr = ('#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n'
           '# ============================================================================\n'
           '# DEPRECATED（2026-10-25）—— 本文件是 v3 期的老 fork，tool-route 判据仍是\n'
           '#   `len(acts) >= 2` 硬编码，且 TOOLS 只发极少工具。\n'
           '# 当前口径唯一入口：eval/eval_kitty_v6.py（60 工具真实 schema + agent loop +\n'
           '#   need=min(2,len(actions)) + reasoning 回退 + --repeat 多数票）。\n'
           '# 选跑器请写死 v6，不要再引用本文件，否则对照会跑错口径。\n'
           '# ============================================================================\n')
    # 去掉原前两行的 shebang/coding，换成新头
    lines = s.splitlines(True)
    body = "".join(lines[2:]) if lines[:2] and (lines[0].startswith("#!") or "coding" in lines[1]) else s
    open(p, "w", encoding="utf-8").write(hdr + body)
    print("DEPRECATED 头已写入", p)
else:
    print("已有 DEPRECATED，跳过")
# 顺带核实老 fork 的 need
import re
s2 = open(p, encoding="utf-8").read()
m = [l.strip() for l in s2.splitlines() if "len(acts)" in l]
print("老 fork 的判据行:", m[:3])
