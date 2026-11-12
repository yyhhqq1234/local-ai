#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_toolname_gate.py — P1 门禁：训练集里的工具名必须落在白名单内

## 为什么（mix-v5 缺陷 D2）
RE 评测 G29 里模型吐了 `kitty_interceptor` —— 全库 0 命中，是按模板自造的名字。
机制：`选它的理由：X（通道 Y）` 模板学会后，工具名成了无监督自由变量。
门禁目标：让「数据里出现目录外工具名」这件事在**开训前**暴露。

## 白名单口径（实测 kitty 数据 26 个名字 / 920 次）
  A  kitty_*            规模工具（kitty_ce 280、kitty_x64dbg 32、kitty_engines 32 …）
  B  harness 工具        read 63、grep 20、pwsh 204、ops_bash 20、job_output 34
                         —— 这些是工作台真实会调的，属于合法域
  C  suspect            A/B 之外的一切（例：`mcp__godot-ai__session_manage`、`kitty_interceptor`）

## 判据
  ① 2A 段出现任何工具名 ⇒ FAIL（负例集必须是纯文本问答）
  ② 任意段出现 suspect 名字 ⇒ FAIL（除非 --allow 显式放行）
  ③ kitty 段工具名种类/次数只报告

退出码 0 通过 / 1 不通过
"""
import argparse
import io
import json
import os
import re
import sys
from collections import Counter

TCALL = re.compile(r"<tool_call>\s*\{[^}]*?\"name\"\s*:\s*\"([^\"]+)\"", re.S)
CALL = re.compile(r"\[CALL\s+([a-z_]+)\]")

HARNESS = {
    "read", "grep", "glob", "pwsh", "bash", "ops_bash", "ops_read_files",
    "job_output", "job_kill", "job_list", "write", "edit",
    "task", "send_message", "list_agents", "spawn_teammate",
}


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def classify(name):
    if name.startswith("kitty_"):
        return "A"
    if name in HARNESS:
        return "B"
    return "C"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", default="train/lines/9b-oxcoder/data/_legacy/mix-v7.jsonl")
    ap.add_argument("--allow", action="append", default=[],
                    help="显式放行的 suspect 名字（可多次给）")
    args = ap.parse_args()
    if not os.path.isfile(args.data):
        sys.exit("[FATAL] 不存在: %s" % args.data)

    per_src = {}
    names = Counter()
    for line in io.open(args.data, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        src = o.get("_mix_src", "?")
        src = "2A" if ("2a" in src or "evalshape" in src or "rawfix" in src) else src
        a = asst(o)
        found = TCALL.findall(a) + CALL.findall(a)
        s = per_src.setdefault(src, dict(rows=0, with_tool=0, names=Counter()))
        s["rows"] += 1
        if found:
            s["with_tool"] += 1
        for n in found:
            s["names"][n] += 1
            names[n] += 1

    print("=" * 80)
    print("工具名白名单门禁 —— %s" % os.path.basename(args.data))
    print("=" * 80)
    print("  %-8s %7s %10s %8s" % ("源", "行数", "含工具调用", "名字种类"))
    for src, s in sorted(per_src.items()):
        print("  %-8s %7d %9d(%4.1f%%) %8d"
              % (src, s["rows"], s["with_tool"], 100.0 * s["with_tool"] / s["rows"],
                 len(s["names"])))

    suspect = Counter({n: c for n, c in names.items()
                       if classify(n) == "C" and n not in args.allow})
    print("")
    print("  名字分类：A kitty_* %d 种 · B harness %d 种 · C suspect %d 种"
          % (sum(1 for n in names if classify(n) == "A"),
             sum(1 for n in names if classify(n) == "B"),
             sum(1 for n in names if classify(n) == "C")))

    bad = []
    if "2A" in per_src and per_src["2A"]["with_tool"] > 0:
        bad.append("2A 段有 %d 行含工具调用（负例必须是纯文本问答）" % per_src["2A"]["with_tool"])
    if suspect:
        for n, c in suspect.most_common():
            bad.append("目录外工具名 `%s` × %d（不属 kitty_* / harness；如确属合法请 --allow）" % (n, c))

    print("")
    if bad:
        for b in bad:
            print("  [FAIL] %s" % b)
        sys.exit(1)
    print("  总判定：PASS —— 工具名全部落在白名单内，2A 段无工具调用")


if __name__ == "__main__":
    main()
