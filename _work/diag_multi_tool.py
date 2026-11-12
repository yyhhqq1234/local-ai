# -*- coding: utf-8 -*-
"""定向微调前的数据诊断：训练集里「多给工具」与「参数不全」各占多少

背景（TASKPOINT §A23.4）：v4 在 E2 条件下 6 条失手里，4 条是
  G12 多选 kitty_dbg,kitty_x64dbg（应只 x64dbg）
  G13 多选 kitty_ce,kitty_prot,kitty_wpb（应只 ce）
  G19 kitty_km 参数不全
  G31 kitty_dnspy 参数不全
猜想：这两类错误是训练数据教的（样本里就爱多给、参数就常缺）。

本脚本只读，回答三个问题：
  1 一条 assistant 里出现几个工具名（分布）
  2 多给工具的样本里，有多少是「其实只需一个」
  3 参数形态：action=/op=/JSON 各占多少，有多少样本给了 action 但没给它的必填项
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
P = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

raw = json.load(io.open(TOOLS, encoding="utf-8"))
ACTIONS = {t["name"]: set(t.get("actions") or []) for t in raw}
VALID = set(ACTIONS)
TOOL_RE = re.compile(r"\b((?:kitty|reverse)_[a-z0-9_]+)\b")


def longest_set(text):
    got = {x for x in TOOL_RE.findall(text) if not x.endswith("_") and x in VALID}
    return {x for x in got if not any(x != y and x in y for y in got)}


n = 0
cnt_dist = Counter()
multi = []
has_action = has_op = has_json = none_arg = 0
bad_action = []   # action 值不在该工具的 enum 里
for line in io.open(P, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n += 1
    o = json.loads(line)
    asst = next((str(m["content"]) for m in o["messages"] if m.get("role") == "assistant"), "")
    tools = longest_set(asst)
    cnt_dist[len(tools)] += 1
    if len(tools) >= 2:
        multi.append((n, sorted(tools), asst[:160].replace("\n", "⏎")))

    if re.search(r"action\s*=", asst):
        has_action += 1
        for m in re.finditer(r"(kitty_[a-z0-9_]+)[^\n]{0,40}?action\s*=\s*([a-z0-9_]+)", asst):
            tn, av = m.group(1), m.group(2)
            if tn in ACTIONS and ACTIONS[tn] and av not in ACTIONS[tn]:
                bad_action.append((n, tn, av, sorted(ACTIONS[tn])[:6]))
    if re.search(r"\bop\s*=", asst):
        has_op += 1
    if re.search(r"\{[^{}]*\"(action|op)\"", asst):
        has_json += 1
    if not (tools or re.search(r"action\s*=|op\s*=|\{", asst)):
        none_arg += 1

print("=" * 96)
print("训练集参数形态诊断：%s（%d 行）" % (os.path.basename(P), n))
print("=" * 96)
print("  assistant 里出现的工具名个数分布：")
for k in sorted(cnt_dist):
    print("      %d 个工具：%5d 行 (%.1f%%)" % (k, cnt_dist[k], cnt_dist[k] * 100.0 / n))
print()
print("  多工具样本合计 %d 行 (%.1f%%)" % (sum(v for k, v in cnt_dist.items() if k >= 2),
                                          sum(v for k, v in cnt_dist.items() if k >= 2) * 100.0 / n))
print("  参数形态：action= %d · op= %d · JSON %d · 完全无参数 %d"
      % (has_action, has_op, has_json, none_arg))
print()
print("  ★ action 值不在该工具 enum 内：%d 处" % len(bad_action))
for ln, tn, av, enum in bad_action[:8]:
    print("      行 %-6d %s action=%s  合法=%s" % (ln, tn, av, enum))
print()
print("  多工具样本样例（前 8 条）：")
for ln, tools, head in multi[:8]:
    print("      行 %-6d %-46s %s…" % (ln, ",".join(tools), head[:100]))
