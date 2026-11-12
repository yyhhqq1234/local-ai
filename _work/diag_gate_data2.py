# -*- coding: utf-8 -*-
"""修正拒写识别后重算 v4b 的 system × 拒/答 交叉

上一版 diag_gate_data.py 的正则漏判了「软拒」：
  「我不打算绕过去写——需要你明确标记」
  「这条超出常规模式范围，先不生成」
  「按常规模式处理」「情节照推、描写收着」
这些本质都是拒写（拒了原要求的露骨写法，给了降级版），但没被算进去。
⇒ 18.9% 是**低估**的，真实值可能接近评测所需的 50%

本脚本用扩展正则重算，回答一个问题：v4b 到底够不够。
"""
import io
import json
import os
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
TRAIN = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train-deleak.jsonl")

# 硬拒 + 软拒 统一识别
REFUSE = re.compile(
    r"(不能|不便|无法|恕不|不提供|不会提供|拒绝|抱歉|不适合|不予"
    r"|不打算|不生成|不按你给|先停|需要你(?:明确)?(?:标记|标注|显式)"
    r"|需要(?:显式|明确)标记|补一个 ?NSFW|标注 ?NSFW|超[出越].{0,8}(范围|模式|范畴)"
    r"|按常规模式|降级|非露骨|描写收着|收着写|不绕过去)"
)

def sys_of(o):
    return next((str(m.get("content", "")) for m in o["messages"] if m.get("role") == "system"), "")

def asst_of(o):
    return "".join(str(m.get("content", "")) for m in o["messages"] if m.get("role") == "assistant")

def norm_sys(s):
    s = (s or "").strip()
    if not s:
        return "(无system)"
    if "许可" in s:
        return "许可"
    if "常规" in s:
        return "常规"
    return "其它"

cross = defaultdict(lambda: {"拒": 0, "答": 0})
n = 0
for line in io.open(TRAIN, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n += 1
    o = json.loads(line)
    sk = norm_sys(sys_of(o))
    a = asst_of(o)
    cross[sk]["拒" if REFUSE.search(a[:300]) else "答"] += 1

print("=" * 88)
print("修正识别后：system × 拒/答（判定窗口 = assistant 前 300 字）")
print("=" * 88)
print("  %-10s %8s %8s %8s %9s" % ("system", "拒", "答", "合计", "拒占比"))
print("  " + "-" * 62)
for sk in sorted(cross, key=lambda x: -sum(cross[x].values())):
    d = cross[sk]
    tot = d["拒"] + d["答"]
    print("  %-10s %8d %8d %8d %8.1f%%" % (sk, d["拒"], d["答"], tot, d["拒"] * 100.0 / tot))

d = cross.get("常规", {"拒": 0, "答": 0})
tot = d["拒"] + d["答"]
print()
print("  ★ 常规组：拒 %d / 答 %d → 拒占 %.1f%%（评测理想 54.5%%）"
      % (d["拒"], d["答"], d["拒"] * 100.0 / max(tot, 1)))
gap = 54.5 - d["拒"] * 100.0 / max(tot, 1)
if gap <= 10:
    print("     ⇒ ✅ 与评测比例差 %.1f pt，可直接训" % gap)
elif gap <= 20:
    print("     ⇒ ⚠ 差 %.1f pt，略偏低但可试" % gap)
else:
    print("     ⇒ ★ 差 %.1f pt，仍需补拒写" % gap)

lp = cross.get("许可", {"拒": 0, "答": 0})
print("  许可组：拒 %d / 答 %d → 拒占 %.1f%%（应接近 0，许可下不该拒）"
      % (lp["拒"], lp["答"], lp["拒"] * 100.0 / max(lp["拒"] + lp["答"], 1)))
