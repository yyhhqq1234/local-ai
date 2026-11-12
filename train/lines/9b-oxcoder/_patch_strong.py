#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性补丁：strong 数据集的手写组去重后再提权 5 份（共 6 份）"""
import io, os, re

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_build_zb_v5_full.py")
s = io.open(P, encoding="utf-8").read()
orig = s

s = s.replace(
    "    rows.extend(old * 6)          # 评测实测错点，权重最高",
    "    rows.extend(old)              # 先放 1 份参与去重")

# 在去重循环结束后插入提权
s = re.sub(
    r"(\n        out\.append\(r\)\n)(\n    with io\.open\(OUT)",
    r"\1    out.extend(old * 5)          # 去重后补 5 份：手写错点组共 6 份\n\2",
    s, count=1)

io.open(P, "w", encoding="utf-8").write(s)
print("[OK]" if s != orig else "[WARN] 未改动")
for ln in s.split("\n"):
    if "rows.extend(old" in ln or "out.extend(old" in ln:
        print("  ", ln)
