#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""就地修正 _rebuild_2b_v3.py 的开关词位置权重与 mode1 插点逻辑"""
import io, os, sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_rebuild_2b_v3.py")
src = io.open(P, encoding="utf-8").read()

OLD_W = "TRIG_MODE_WEIGHTS = [(0, 60), (1, 25), (2, 15)]"
NEW_W = "TRIG_MODE_WEIGHTS = [(0, 50), (1, 30), (2, 20)]"

OLD_M1 = '''    if mode == 1:
        parts = rest.split("\\n\\n", 1)
        if len(parts) == 2 and len(parts[1].strip()) > 40:
            return f"{parts[0]}\\n\\n{trig}\\n\\n{parts[1]}"
        return f"{trig} {rest}"'''

NEW_M1 = '''    if mode == 1:
        parts = rest.split("\\n\\n", 1)
        if len(parts) == 2 and len(parts[1].strip()) > 40:
            head, tail_ = parts[0], parts[1]
            # 首段太短则再切一段，确保开关词不出现在最前面
            if len(head.strip()) < 20 and "\\n\\n" in tail_:
                h2, t2 = tail_.split("\\n\\n", 1)
                return f"{head}\\n\\n{h2}\\n\\n{trig}\\n\\n{t2}"
            return f"{head}\\n\\n{trig}\\n\\n{tail_}"
        return f"{trig} {rest}"'''

n = 0
if OLD_W in src:
    src = src.replace(OLD_W, NEW_W); n += 1
else:
    print("[WARN] 权重行未命中（可能已改）")
if OLD_M1 in src:
    src = src.replace(OLD_M1, NEW_M1); n += 1
else:
    print("[WARN] mode1 段未命中")

io.open(P, "w", encoding="utf-8").write(src)
print(f"[OK] 替换 {n} 处")
