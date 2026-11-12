# -*- coding: utf-8 -*-
"""拒写识别的第三版：只看 assistant 开头，且排除「正文里的否定词」误判

前两版的问题：
  v1 正则太窄 → 漏掉软拒（「我不打算绕过去写」）→ 常规组算出 18.9%（严重低估）
  v2 正则放宽到全文前 300 字 → 许可组误判 753 行
     （正文里「总不能说快跳吧」「可不能随便旷课」「非但没有拒绝」全被当成拒写）

v3 规则：
  ① 只看 assistant 前 80 字（拒写一定是开场就表明）
  ② 开头不能是叙事形态（引号/全角缩进/对话）—— 有这些就是正文
  ③ 拒绝语用明确句式表，不用宽泛的「不能/无法」
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

STRICT = re.compile(
    r"(我不打算|我不写|这条超出|这条不(?:行|能)|先不生成|先停|先按一般向|按常规|"
    r"需要你(?:明确)?(?:标记|标注|显式)|需要(?:显式|明确)标记|补一个 ?NSFW|"
    r"没有开关|不带授权标记|不能默认|超出常规|降级成非露骨|非露骨版|描写收着)"
)
NARRATIVE = re.compile(r'^[\s　"「『“（(]')

def is_refuse(a):
    head = (a or "").lstrip()[:80]
    if not head:
        return False
    if NARRATIVE.match(head):        # 开场就是叙事/对话 → 正文，不是拒写
        return False
    return bool(STRICT.search(head))

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
samples = defaultdict(list)
n = 0
for line in io.open(TRAIN, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n += 1
    o = json.loads(line)
    sk = norm_sys(sys_of(o))
    a = asst_of(o)
    r = is_refuse(a)
    cross[sk]["拒" if r else "答"] += 1
    if len(samples[(sk, "拒" if r else "答")]) < 2:
        samples[(sk, "拒" if r else "答")].append(a[:90].replace("\n", "⏎"))

print("=" * 88)
print("v3 精确识别（前 80 字 + 排除叙事开场）· %d 行" % n)
print("=" * 88)
print("  %-10s %8s %8s %8s %9s" % ("system", "拒", "答", "合计", "拒占比"))
print("  " + "-" * 62)
for sk in sorted(cross, key=lambda x: -sum(cross[x].values())):
    d = cross[sk]
    tot = d["拒"] + d["答"]
    print("  %-10s %8d %8d %8d %8.1f%%" % (sk, d["拒"], d["答"], tot, d["拒"] * 100.0 / tot))

for (sk, kind), ss in samples.items():
    print()
    print("  [%s × %s] 样例：" % (sk, kind))
    for s in ss:
        print("      %s" % s)

d = cross.get("常规", {"拒": 0, "答": 0})
tot = max(d["拒"] + d["答"], 1)
r = d["拒"] * 100.0 / tot
print()
print("  ★ 常规组拒占比 %.1f%%（评测理想 54.5%%）→ 差 %+.1f pt" % (r, r - 54.5))
lp = cross.get("许可", {"拒": 0, "答": 0})
lr = lp["拒"] * 100.0 / max(lp["拒"] + lp["答"], 1)
print("  ★ 许可组拒占比 %.1f%%（应接近 0）" % lr)
