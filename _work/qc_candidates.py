# -*- coding: utf-8 -*-
"""V2 候选集数据质检：答案里的工具必须在候选集里，否则训练信号自相矛盾

检查项：
  1 每条样本 assistant 用到的 kitty_/reverse_ 工具是否都在 system 候选集出现
  2 候选集大小是否稳定在 8-12
  3 候选集是否混入"不存在的工具名"（不应该有）
  4 负向样本（assistant 不含工具）占比与处理是否合理
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")
P = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    L9B, "data", "kitty-reverse", "mix-z-re-v2-cand-train.jsonl")

raw = json.load(io.open(TOOLS, encoding="utf-8"))
VALID = {t["name"] for t in raw}
TOOL_RE = re.compile(r"\b((?:kitty|reverse)_[a-z0-9_]+)\b")


def longest_set(text):
    """抽最长匹配的工具名集合（避免 kitty_rea 覆盖 kitty_rea_compare）"""
    got = set(TOOL_RE.findall(text))
    out = set()
    for x in got:
        if not any(x != y and x in y for y in got):
            out.add(x)
    return out


n = 0
missing_any = []          # 答案工具不在候选集
cand_sizes = Counter()
neg = 0
bad_cand = 0
for line in io.open(P, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n += 1
    o = json.loads(line)
    msgs = o["messages"]
    sys_txt = next((str(m["content"]) for m in msgs if m.get("role") == "system"), "")
    asst = next((str(m["content"]) for m in msgs if m.get("role") == "assistant"), "")

    # 候选集 = system 里形如 "- kitty_xxx:" 的行
    cands = set(re.findall(r"^-\s+((?:kitty|reverse)_[a-z0-9_]+):", sys_txt, re.M))
    cand_sizes[len(cands)] += 1
    if cands - VALID:
        bad_cand += 1

    need = longest_set(asst)
    # 排除两类良性命中：
    #  ① 以 _ 结尾的通配写法（reverse_add_* 这类列表表达，并非真实工具名）
    #  ② antifake 反例样本（明确声明「没有 kitty_watch / kitty_monitor 这类工具」）
    need = {x for x in need if not x.endswith("_") and x in VALID}
    if not need:
        neg += 1
        continue
    missing = need - cands
    if missing:
        missing_any.append((n, sorted(missing), sorted(cands)[:6]))

print("=" * 90)
print("V2 候选集质检：%s" % os.path.basename(P))
print("=" * 90)
print("  样本 %d" % n)
print("  候选集大小分布：%s" % dict(sorted(cand_sizes.items())))
print("  含非法候选名（不在 64 白名单）：%d  %s" % (bad_cand, "✅" if bad_cand == 0 else "★"))
print("  负向样本（assistant 无工具调用）：%d (%.1f%%)" % (neg, neg * 100.0 / n))
print("  ★答案工具不在候选集（信号矛盾）：%d 行 (%.2f%%)"
      % (len(missing_any), len(missing_any) * 100.0 / n))
for ln, miss, cands in missing_any[:10]:
    print("      行 %-6d 缺=%s  候选=%s…" % (ln, miss, cands))
if len(missing_any) > 10:
    print("      ... 共 %d 行" % len(missing_any))
verdict = ("✅ 可直接训练" if not missing_any and bad_cand == 0
           else "★ 需修：候选集漏了答案所用工具，模型会被要求选一个不在列表里的东西")
print()
print("  判定：%s" % verdict)
