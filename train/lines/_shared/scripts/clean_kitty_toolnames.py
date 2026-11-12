#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""clean_kitty_toolnames.py — 剔除 kitty 训练集里「目录外工具名」的行（P1 数据侧清理）

## 门禁发现了什么（2026-10-30 16:20）
`check_toolname_gate.py` 在 mix-v7 上报 FAIL：kitty 段有 7 个不属于工具箱的名字，共 44 次调用
（占 23718 行的 **0.19%**，全部 `meta.__stage == "re"`）：

    mcp__godot-ai__session_manage ×20 · mcp__godot-ai__project_run ×4
    agent_teams_status ×4 · agent_teams_claim_task ×4
    skill ×4 · dev_stage_add ×4 · dev_plugin_status ×4

这些是 DSH 平台 / Godot 工程的工具，不是 kitty 逆向工具台的工具。
留在数据里等于教模型「逆向现场可以调 godot/agent_teams」——**这正是 kitty_interceptor 类编造的同源土壤**。

## 处置
整行丢弃（不做局部修补）：这些行的任务本体就是 DSH/Godot 的事，删掉比缝补干净。
kitty 保留 **23718 − 44 = 23674 行（99.81%）**，主线不受影响。

产物：train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl（原文件不动）
"""
import io
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-bucketed.jsonl")
OUT = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-clean.jsonl")

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


def out_of_catalog(a):
    names = TCALL.findall(a) + CALL.findall(a)
    return [n for n in names if not n.startswith("kitty_") and n not in HARNESS]


def main():
    if not os.path.isfile(SRC):
        sys.exit("[FATAL] 缺 %s" % SRC)
    kept, dropped = [], 0
    per = Counter()
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        bad = out_of_catalog(asst(o))
        if bad:
            dropped += 1
            for n in bad:
                per[n] += 1
            continue
        kept.append(o)

    os.makedirs(os.path.dirname(os.path.abspath(OUT)) or ".", exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fo:
        for o in kept:
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")

    chars = sum(len(asst(o)) for o in kept)
    print("源 %d 行 → 保留 %d 行（丢弃 %d 行，%.2f%%）"
          % (len(kept) + dropped, len(kept), dropped, 100.0 * dropped / (len(kept) + dropped)))
    print("  丢弃原因（按工具名）：%s" % dict(per))
    print("  保留部分 assistant 字符 %d" % chars)
    print("  → %s" % OUT)

    # 复核：产物里不应再有目录外名字
    left = 0
    for line in io.open(OUT, encoding="utf-8"):
        if line.strip() and out_of_catalog(asst(json.loads(line))):
            left += 1
    print("  复核：产物中仍含目录外工具名的行 = %d（须 0）" % left)
    if left:
        sys.exit(1)


if __name__ == "__main__":
    main()
