#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""负例自证：把 verify_deliver1.sh 里判据七的那段 python **原样抽出来**，喂 4 个回答看判定。
证明新口径（hint 读题 / gib 乱码）能红，且不冤枉正常回答。"""
import io
import re
import sys

S = "tmp/deliver/verify_deliver1.sh"
src = open(S, encoding="utf-8").read()
m = re.search(r"CHK=\$\(printf '%s' \"\$CONTENT\" \| \"\$PY\" -c \"(import sys,re;.*?print\(f'\{n\} \{cjk\} \{pct:\.1f\} \{hint\} \{gib\} \{br:\.3f\}'\))\"", src, re.S)
if not m:
    sys.exit("[FATAL] 抽不出判据七 python 片段")
code = m.group(1).replace('\\"', '"')
print("[extract] 判据七片段 %d 字符（从脚本原样抽取，未改写）" % len(code))

CASES = [
    ("正常答题（0x1000/节表）",
     "PE 里 RVA 是相对镜像基址的偏移，File Offset 是文件内偏移；节表里 0x1000 是节对齐，0x200 是文件对齐。", "PASS"),
    ("模板套话（没读题）",
     "这是一个很好的问题。简单来说，两者都是位置描述方式，区别在于所处的坐标系不同，理解它们有助于分析程序结构。", "FAIL(未读题)"),
    ("乱码（ÿþý 连串）",
     "PE RVA \u00ff\u00fe\u00fd\u00fc\u00fb\u00fa\u00f9 偏移 节 对齐 说明 结构 理解 有助 分析 程序", "FAIL(乱码特征)"),
    ("极短", "抱歉", "FAIL(短/占比)"),
]

real_stdin = sys.stdin
for name, text, want in CASES:
    sys.stdin = io.StringIO(text)
    g = {"__name__": "chk"}
    exec(compile(code, "<chk>", "exec"), g)  # noqa: S102
    print("  %-20s 期望 %-14s → len=%-3s cjk=%-3s pct=%-5s hint=%s gib=%s" % (
        name, want, g.get("n"), g.get("cjk"), round(float(g.get("pct", 0)), 1),
        g.get("hint"), g.get("gib")))
sys.stdin = real_stdin
