# -*- coding: utf-8 -*-
"""定位 gate_leak 0.6333 的根因：检查 v5 训练集里「拒写」样本的 assistant 是否夹带露骨词

假设：模型学会了「拒 + 顺带写点露骨的」，因为训练集的拒写样本本身就是这么写的
     （v5 里有 3364 条常规×拒写，它们的 assistant 多为「我不打算写…非露骨版可以这么走：<描述>」）

判据：统计这些拒写样本里露骨词的出现次数分布
  · 若大量样本 >0 → 数据教的（修数据即可）
  · 若几乎都是 0 → 不是数据问题，是训练/解码副作用（要换思路）

用法：python _work/diag_leak_source.py
"""
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
P = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v5.jsonl")

SEX = re.compile(r"乳头|肉棒|龟头|淫|射精|高潮|肏|阴道|阴茎|乳房|阴蒂|精液|小穴|蜜穴|口交|抽插|胴体|"
                 r"肉便器|发情|潮吹|龟|屄|逼|骚|浪叫|淫荡|下体|私处|媚肉|白浊|媚药|春药")
STRICT_REFUSE = re.compile(
    r"(我不打算|我不写|这条超出|这条不(?:行|能)|先不生成|先停|先按一般向|按常规|"
    r"需要你(?:明确)?(?:标记|标注|显式)|需要(?:显式|明确)标记|补一个 ?NSFW|"
    r"没有开关|不带授权标记|不能默认|超出常规|降级成非露骨|非露骨版|描写收着)")
NARRATIVE = re.compile(r'^[\s　"「『“（(]')


def msgs(o):
    return o.get("messages") or []


def sys_of(o):
    return next((str(m.get("content", "")) for m in msgs(o) if m.get("role") == "system"), "")


def asst_of(o):
    return "".join(str(m.get("content", "")) for m in msgs(o) if m.get("role") == "assistant")


def is_refuse(a):
    head = (a or "").lstrip()[:80]
    if not head or NARRATIVE.match(head):
        return False
    return bool(STRICT_REFUSE.search(head))


refuse_rows = []
for line in io.open(P, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    if "常规" not in sys_of(o):
        continue
    a = asst_of(o)
    if is_refuse(a):
        refuse_rows.append(a)

print("=" * 92)
print("v5 训练集「常规 × 拒写」样本的露骨词残留检查")
print("=" * 92)
print("  拒写样本数：%d" % len(refuse_rows))

cnt = Counter()
for a in refuse_rows:
    n = len(SEX.findall(a))
    if n == 0:
        cnt["0"] += 1
    elif n <= 2:
        cnt["1-2"] += 1
    elif n <= 5:
        cnt["3-5"] += 1
    elif n <= 10:
        cnt["6-10"] += 1
    else:
        cnt["11+"] += 1

total = len(refuse_rows)
print()
print("  露骨词出现次数分布：")
for k in ("0", "1-2", "3-5", "6-10", "11+"):
    v = cnt.get(k, 0)
    print("    %-6s %5d 条 (%.1f%%)" % (k, v, v * 100.0 / max(total, 1)))

dirty = total - cnt.get("0", 0)
print()
print("  ★ 含露骨词的拒写样本：%d / %d = %.1f%%" % (dirty, total, dirty * 100.0 / max(total, 1)))
if dirty * 100.0 / max(total, 1) > 20:
    print("     ⇒ 与 gate_leak 0.6333 方向一致：**是数据教的**（拒写回答里夹带露骨词）")
    print("     ⇒ 修法：清掉这些样本 assistant 里的露骨片段，或整条改成纯拒绝版")
else:
    print("     ⇒ 比例低，leak 主要不是数据造成的，需查训练/解码侧")

print()
print("  含露骨词最多的 3 条样例：")
scored = sorted(((len(SEX.findall(a)), a) for a in refuse_rows), reverse=True)
for n, a in scored[:3]:
    print("    --- 露骨词 %d 个 ---" % n)
    print("    %s" % a[:320].replace("\n", "\n    "))
    print()

# 关键：看露骨词出现在「拒绝语之后」还是之前
print("  位置分析（露骨词是否出现在拒绝语之后）：")
after = 0
for a in refuse_rows:
    m = STRICT_REFUSE.search(a.lstrip()[:80])
    if not m:
        continue
    tail = a[m.end():]
    if SEX.search(tail):
        after += 1
print("    拒绝语之后仍有露骨词：%d 条 (%.1f%%)" % (after, after * 100.0 / max(total, 1)))
if after * 100.0 / max(total, 1) > 20:
    print("    ⇒ 模型学到「先拒，再写点露骨的」这一模式 —— 这就是 leak 的直接来源")
