#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scan_silent_patterns.py -- 用「已发现的五种静默错模式」反扫全部脚本，找第八例。

模式：
  P1  x = f(p) if os.path.exists(p) else [] / else None     缺失被默认值吸收
  P2  .get(k, <非 None 默认值>)                              缺失被默认值吸收
  P3  except: pass / except: continue                        异常被吞
  P4  函数体内出现全大写模块常量（SRC/OUT/EVAL/DATA/…）      参数传了但没用
  P5  输出串里出现 N/A 或 "-" 占位                           降级无人知

用法：python tmp/audit/scan_silent_patterns.py [--json]
只报告，不改文件；每条命中都要人判「是不是真缺陷」。
"""
import json
import os
import re
import sys

KITTY = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(KITTY, "scripts")

# 模块常量白名单：出现在函数体里但确实是"设计如此"的
CONST_OK = {"SCREEN_W", "SCREEN_H", "VRAM_BUDGET_GIB", "PER_LAYER_4BIT_GIB", "HEAD_GIB",
            "ACT_GIB", "TRAIN", "RULES", "SYS", "TOOLS"}
# 只盯"路径型"模块常量：这些一旦被写死在函数体里，参数就白传了
PATH_CONSTS = {"SRC", "OUT", "OUTDIR", "EVAL", "DATA", "FORGE", "BASE", "DATASET",
               "ROOT", "DST", "MERGE", "SOURCE", "TARGET"}

PATS = [
    ("P1_exists_else", re.compile(r"if\s+os\.path\.exists\([^)]*\)\s*else\s*(\[\]|None|\{\})")),
    ("P2_get_default", re.compile(r"\.get\(\s*[\"'][\w-]+[\"']\s*,\s*(?!None)[^)]+\)")),
    ("P3_except_pass", re.compile(r"except[^\n]*:\s*\n\s*(pass|continue)\b")),
    ("P5_na", re.compile(r"N/A|\bn/?a\b")),
]
CONST_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def func_ranges(lines):
    """返回 [(func_name, start, end)] —— 粗粒度，够用来判"在函数体内"。"""
    out, cur = [], None
    for i, l in enumerate(lines):
        m = re.match(r"^(\s*)def\s+(\w+)", l)
        if m:
            if cur:
                out.append((cur[0], cur[1], i - 1))
            cur = (m.group(2), i)
    if cur:
        out.append((cur[0], cur[1], len(lines) - 1))
    return out


def scan_file(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    hits = []

    for name, rx in PATS:
        for m in rx.finditer(src):
            ln = src[:m.start()].count("\n") + 1
            hits.append({"pattern": name, "line": ln,
                         "text": lines[ln - 1].strip()[:120]})

    fr = func_ranges(lines)
    for fname, a, b in fr:
        for i in range(a, min(b + 1, len(lines))):
            l = lines[i]
            if l.strip().startswith("#") or "def " in l:
                continue
            for m in CONST_RE.finditer(l):
                c = m.group(1)
                if c not in PATH_CONSTS:
                    continue
                hits.append({"pattern": "P4_const_in_func", "line": i + 1,
                             "text": f"[{fname}] " + l.strip()[:110], "const": c})
    return hits


def main():
    files = sorted(f for f in os.listdir(SCRIPTS) if f.endswith(".py"))
    total = {}
    report = {}
    for f in files:
        h = scan_file(os.path.join(SCRIPTS, f))
        if h:
            report[f] = h
            for x in h:
                total[x["pattern"]] = total.get(x["pattern"], 0) + 1
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    print(f"扫描 {len(files)} 个脚本，命中 {sum(total.values())} 处："
          + "  ".join(f"{k}={v}" for k, v in sorted(total.items())) + "\n")
    for f, hits in sorted(report.items(), key=lambda kv: -len(kv[1])):
        print(f"== {f}  ({len(hits)})")
        for x in hits[:12]:
            print(f"   [{x['pattern']:16s}] L{x['line']:<4d} {x['text']}")
        if len(hits) > 12:
            print(f"   … 另有 {len(hits) - 12} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
