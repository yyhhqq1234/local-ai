#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_notool_gate.py — 开训前硬门禁：2A 段不许出现工具调用，且必须带「禁工具」指令

## 依据（mix-v5 缺陷分析）
  mix-v5 的 2A 答卷 16/40 吐了 `<tool_call>`，这 16 题 Δcov −0.448、零例变好；
  没吐的 24 题 +0.107。⇒ 工具调用一旦跨域泄漏，聚合指标必被拖死。
  这条门禁就是让同类缺陷「开训前」暴露，而不是等 4 小时训练 + 3.5 小时评测之后。

## 判据（一票否决）
  ① 2A 段 assistant 含 `<tool_call>` / `<tool_response>` 的行数 == 0
  ② 2A 段 system 必须含工具禁令关键字（no filesystem / Never emit <tool_call>）
  ③ 2A 段含完整代码块比例 >= 0.95
  ④ kitty 段的 tool_call 比例只做报告（那是 RE 正例，不判）

退出码：0 通过 / 1 不通过
"""
import io
import json
import os
import sys

TOOL_MARKS = ("<tool_call>", "<tool_response>")


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def sysmsg(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "system")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "train/lines/9b-oxcoder/data/_legacy/mix-v6.jsonl"
    if not os.path.isfile(path):
        sys.exit("[FATAL] 不存在: %s" % path)

    stat = {}
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        src = o.get("_mix_src", "?")
        if src.startswith("traj-2a") or "evalshape" in src:
            src = "2A"
        elif src == "kitty":
            src = "kitty"
        s = stat.setdefault(src, dict(n=0, tool=0, code=0, sys_ok=0))
        a = asst(o)
        s["n"] += 1
        if any(m in a for m in TOOL_MARKS):
            s["tool"] += 1
        if a.count("```") >= 2:
            s["code"] += 1
        sm = sysmsg(o)
        if ("no filesystem" in sm) or ("Never emit <tool_call>" in sm):
            s["sys_ok"] += 1

    print("=" * 78)
    print("禁工具门禁 —— %s" % os.path.basename(path))
    print("=" * 78)
    print("  %-8s %7s %9s %10s %10s" % ("源", "行数", "tool_call", "代码块%", "带禁令%"))
    bad = []
    for src, s in sorted(stat.items()):
        tp = 100.0 * s["tool"] / s["n"]
        cp = 100.0 * s["code"] / s["n"]
        sp = 100.0 * s["sys_ok"] / s["n"]
        print("  %-8s %7d %9d %9.1f%% %9.1f%%" % (src, s["n"], s["tool"], cp, sp))
        if src == "2A":
            if s["tool"] != 0:
                bad.append("2A 段 %d 行含工具标记（须 0）" % s["tool"])
            if sp < 1.0:
                bad.append("2A 段仅 %.1f%% 带工具禁令（须 100%%）" % sp)
            if cp < 95.0:
                bad.append("2A 段代码块率 %.1f%% < 95%%" % cp)

    print("")
    if bad:
        for b in bad:
            print("  [FAIL] %s" % b)
        sys.exit(1)
    print("  总判定：PASS —— 2A 段无工具调用、带禁令、代码块达标")


if __name__ == "__main__":
    main()
