# -*- coding: utf-8 -*-
"""定向微调第 1 步：修训练集里 255 处「action 值不在该工具 enum 内」

诊断依据（_work/diag_multi_tool.py）：
  7562 行里有 255 处 action 值非法，涉及 212 行（2.8%），17 种组合
  最大头：kitty_die action=detect ×173（合法只有 scan/status）
  ⇒ 模型是从这些样本里学会写错 action 的，这直接解释「参数错」类失分

策略：只做有明确 1:1 语义对应的映射；需要改形态的（kitty_ce find/pread 应写成 op=...）
     不硬改，逐条跳过并计数，避免引入新错误。

产物：
  mix-z-re-v4-actfix.jsonl   全量修正版（7562 行）
  _work/action_fix_report.json  修复统计
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
SRC = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
OUT = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-actfix.jsonl")
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

raw = json.load(io.open(TOOLS, encoding="utf-8"))
ACTS = {t["name"]: set(t.get("actions") or []) for t in raw}

# 语义 1:1 映射（左侧必须确实是右侧的动作面的同义表达）
FIX = {
    ("kitty_die", "detect"): "scan",        # DIE 的检测动作就是 scan
    ("kitty_frida", "script"): "attach",    # 跑脚本 = attach 后注入
    ("kitty_dnspy", "decompile"): "open",   # dnSpy 只有 open，反编译是 open 之后的事
    ("kitty_dnspy", "import"): "open",
    ("kitty_dnspy", "types"): "open",
    ("kitty_unpack", "scan"): "collect",
    ("kitty_unpack", "probe"): "status",
    ("kitty_unpack", "extract"): "parse",
    ("kitty_wpb", "query"): "write",        # wpb 只有 write
    ("kitty_uedump", "dump"): "collect",
    ("kitty_status", "ensure-bridge"): "probe",
    ("kitty_fmodel", "extract"): "export",
    ("kitty_ghidra", "xrefs"): "search",
}
# 需要改调用形态，不在值级别硬改
SKIP = {("kitty_ce", "find"), ("kitty_ce", "pread"),
        ("kitty_settings", "task-dispatch"), ("kitty_ida", "search")}

RE = re.compile(r"(kitty_[a-z0-9_]+)([^\n]{0,40}?)action\s*=\s*([a-z0-9_-]+)")

fixed = Counter()
skipped = Counter()
still_bad = Counter()
n_rows = touched = 0

with io.open(OUT, "w", encoding="utf-8", newline="\n") as fo:
    for line in io.open(SRC, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        n_rows += 1
        o = json.loads(line)
        asst = next((str(m["content"]) for m in o["messages"] if m.get("role") == "assistant"), "")
        new_asst = asst
        changed = False

        def repl(m):
            global changed
            tn, mid, av = m.group(1), m.group(2), m.group(3)
            if tn not in ACTS or not ACTS[tn] or av in ACTS[tn]:
                return m.group(0)
            key = (tn, av)
            if key in FIX and FIX[key] in ACTS[tn]:
                changed = True
                fixed[key] += 1
                return "%s%saction=%s" % (tn, mid, FIX[key])
            if key in SKIP:
                skipped[key] += 1
                return m.group(0)
            still_bad[key] += 1
            return m.group(0)

        new_asst = RE.sub(repl, asst)
        if changed:
            touched += 1
            for m in o["messages"]:
                if m.get("role") == "assistant":
                    m["content"] = new_asst
        fo.write(json.dumps(o, ensure_ascii=False) + "\n")

# 复检
bad_after = 0
for line in io.open(OUT, encoding="utf-8"):
    o = json.loads(line)
    asst = next((str(m["content"]) for m in o["messages"] if m.get("role") == "assistant"), "")
    for m in RE.finditer(asst):
        tn, av = m.group(1), m.group(3)
        if tn in ACTS and ACTS[tn] and av not in ACTS[tn]:
            bad_after += 1

print("=" * 96)
print("action 值修正")
print("=" * 96)
print("  处理 %d 行 · 受影响 %d 行 · 修掉 %d 处" % (n_rows, touched, sum(fixed.values())))
print("  跳过（需改调用形态，不硬改）：%d 处" % sum(skipped.values()))
for k, v in skipped.most_common():
    print("      %s action=%s ×%d" % (k[0], k[1], v))
if still_bad:
    print("  ★ 未映射（需人工定夺）：%d 处" % sum(still_bad.values()))
    for k, v in still_bad.most_common():
        print("      %s action=%s ×%d" % (k[0], k[1], v))
print()
print("  修正明细：")
for k, v in fixed.most_common():
    print("      %-22s action=%-14s → %-12s ×%d" % (k[0], k[1], FIX[k], v))
print()
print("  复检：剩余非法 action %d 处 %s" % (bad_after, "✅" if bad_after == sum(skipped.values()) + sum(still_bad.values()) else "★"))
print("  → %s" % OUT)

with io.open("_work/action_fix_report.json", "w", encoding="utf-8") as f:
    json.dump({"rows": n_rows, "touched": touched,
               "fixed": {"%s|%s" % k: v for k, v in fixed.items()},
               "fixed_total": sum(fixed.values()),
               "skipped": {"%s|%s" % k: v for k, v in skipped.items()},
               "unmapped": {"%s|%s" % k: v for k, v in still_bad.items()},
               "bad_after": bad_after}, f, ensure_ascii=False, indent=2)
