# -*- coding: utf-8 -*-
"""按真实 schema 修 gen_v6_mix.py 里的错误参数"""
import re
p = "tools/gen_v6_mix.py"
s = open(p, encoding="utf-8").read()
before = s

# 1) kitty_status 没有 action 参数
s = s.replace('("kitty_status", {"action": "status"}', '("kitty_status", {}')
s = s.replace('("kitty_status", {"action": "probe"}', '("kitty_status", {"probe": True}')
# 2) kitty_patch 用 path 不是 target
s = re.sub(r'\("kitty_patch", \{"action": ("[a-z]+"), "target": ', r'("kitty_patch", {"action": \1, "path": ', s)
# 3) kitty_die / kitty_drv / kitty_init 等也用 action —— 它们真实有 action，保留
open(p, "w", encoding="utf-8").write(s)
print("修改行数差:", len(s) - len(before))
print("剩余 kitty_status 带 action:", s.count('("kitty_status", {"action"'))
print("剩余 kitty_patch 带 target:", s.count('"kitty_patch", {"action": "info", "target"'))
