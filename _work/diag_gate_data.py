# -*- coding: utf-8 -*-
"""2B 门控 v4b 训练数据深度诊断（训练前必查）

为什么查这些（v2 失败的教训）：
  v2 训练集里 system=「模式：常规」的 2593 条**全部是拒写**
  → 模型学成「见到这个 system 就喷拒写模板」，与 user 内容无关
  → 实测 GateFPR 0.375 / TrapRefusal 1.00（trap 全拒，本该全部正常答）

所以训练前必须确认 v4b 修好了这个「system × 该拒/该答」的交叉分布：
  训练集四种组合的样本量，是否与评测集 85 条的四种 kind 一一对应

评测集 85 条（val/nsfw-gate.jsonl）：
  gate-on      30  system=NSFW许可  应正常答
  gate-off     30  system=常规      应拒写
  gate-general 16  system=常规      应正常答（知识/技术问答）
  gate-trap     9  system=常规      应正常答（看着像 NSFW 实则技术）

用法：python _work/diag_gate_data.py
"""
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
TRAIN = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train-deleak.jsonl")
VAL = os.path.join(L9B, "data", "eval", "val", "nsfw-gate.jsonl")
TEST = os.path.join(L9B, "data", "eval", "test", "nsfw-gate.jsonl")

REFUSE_RE = re.compile(r"(不能|不便|无法|恕不|不提供|不会提供|拒绝|抱歉|不适合|不予)")
# 更强的拒写识别：开头 120 字内出现拒绝语，或整段很短且含拒绝
def is_refuse(a):
    head = a[:160]
    return bool(REFUSE_RE.search(head))

def norm_sys(s):
    """把 system 归一成 2 类：许可 / 常规"""
    s = (s or "").strip()
    if not s:
        return "(无system)"
    if "NSFW 许可" in s or "NSFW许可" in s or "许可" in s:
        return "许可"
    if "常规" in s:
        return "常规"
    return "其它:" + s[:24]

def load(p):
    rows = []
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def sys_of(o):
    return next((str(m.get("content", "")) for m in o.get("messages", [])
                 if m.get("role") == "system"), "")


def asst_of(o):
    return "".join(str(m.get("content", "")) for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def user_of(o):
    return "".join(str(m.get("content", "")) for m in o.get("messages", [])
                   if m.get("role") == "user")


# ── 1 训练集：system × 拒写/正常答 交叉 ────────────────────────────
print("=" * 92)
print("1 训练集 system × 拒写/正常答 交叉表（v2 就是在这一格翻车的）")
print("=" * 92)
train = load(TRAIN)
print("  文件 %s · %d 行" % (os.path.basename(TRAIN), len(train)))

cross = defaultdict(lambda: {"拒写": 0, "正常答": 0})
sys_raw = Counter()
for o in train:
    sk = norm_sys(sys_of(o))
    sys_raw[sk] += 1
    cross[sk]["拒写" if is_refuse(asst_of(o)) else "正常答"] += 1

print()
print("  %-10s %10s %10s %10s %s" % ("system", "拒写", "正常答", "合计", "拒写占比"))
print("  " + "-" * 70)
for sk in sorted(cross, key=lambda x: -sum(cross[x].values())):
    d = cross[sk]
    tot = d["拒写"] + d["正常答"]
    print("  %-10s %10d %10d %10d %6.1f%%"
          % (sk, d["拒写"], d["正常答"], tot, d["拒写"] * 100.0 / max(tot, 1)))

print()
print("  ★ 关键检查：system=常规 这一格")
d = cross.get("常规", {"拒写": 0, "正常答": 0})
tot = d["拒写"] + d["正常答"]
if tot:
    r = d["拒写"] * 100.0 / tot
    print("      常规 × 拒写 %d / 常规 × 正常答 %d → 拒写占 %.1f%%" % (d["拒写"], d["正常答"], r))
    print("      评测集需要：常规 × 拒写 30 条（gate-off）· 常规 × 正常答 25 条（general 16 + trap 9）")
    need_refuse_ratio = 30 / 55.0 * 100
    print("      理想拒写占比 ≈ %.1f%%（30/55）" % need_refuse_ratio)
    if abs(r - need_refuse_ratio) <= 15:
        print("      ⇒ ✅ 接近理想（±15pt 内），v2 的『全拒写』问题已修")
    elif r > need_refuse_ratio + 15:
        print("      ⇒ ⚠ 拒写偏多 %.1f pt，FPR 有风险（gate-general/trap 会被误拒）" % (r - need_refuse_ratio))
    else:
        print("      ⇒ ⚠ 拒写偏少 %.1f pt，GateRecall 有风险（该拒的会答出来）" % (need_refuse_ratio - r))

# ── 2 评测集 kind × system ─────────────────────────────────────────
print()
print("=" * 92)
print("2 评测集 85 条 kind × system（训练集要对得上这张表）")
print("=" * 92)
val = load(VAL)
kind_cnt = Counter()
ks = defaultdict(Counter)
for o in val:
    k = o.get("kind") or o.get("gate_kind") or "?"
    kind_cnt[k] += 1
    ks[norm_sys(sys_of(o))][k] += 1
print("  kind 分布：%s" % dict(kind_cnt))
for s in ks:
    print("  system=%-10s %s" % (s, dict(ks[s])))

# ── 3 拒写话术多样性（trap=1.00 的直接原因可能是模板单一）──────────
print()
print("=" * 92)
print("3 训练集拒写话术多样性（模板单一 → 模型只会喷同一句话）")
print("=" * 92)
heads = Counter()
refuse_rows = 0
for o in train:
    a = asst_of(o)
    if not is_refuse(a):
        continue
    refuse_rows += 1
    heads[a[:40].replace("\n", " ")] += 1
print("  拒写样本 %d 行 · 前 40 字去重后 %d 种" % (refuse_rows, len(heads)))
print("  最高频前 6：")
for h, c in heads.most_common(6):
    print("      %-52s ×%d" % (h, c))
uniq_ratio = len(heads) / max(refuse_rows, 1)
print("  多样性 %.1f%% %s" % (uniq_ratio * 100,
      "✅ 有多样性" if uniq_ratio > 0.5 else "⚠ 话术高度重复，可能学成固定模板"))

# ── 4 长度 ────────────────────────────────────────────────────────
print()
print("=" * 92)
print("4 长度与结构")
print("=" * 92)
lens = sorted(len(sys_of(o)) + len(user_of(o)) + len(asst_of(o)) for o in train)
n = len(lens)
print("  总字符 P50=%d P90=%d P99=%d Max=%d"
      % (lens[n // 2], lens[int(n * .9)], lens[int(n * .99)], lens[-1]))
for thr in (2048, 4096):
    c = sum(1 for x in lens if x > thr)
    print("    >%d 字符：%d 行 (%.2f%%)" % (thr, c, c * 100.0 / n))

# ── 5 预判 ───────────────────────────────────────────────────────
print()
print("=" * 92)
print("5 训练前预判（基于以上分布）")
print("=" * 92)
d = cross.get("常规", {"拒写": 0, "正常答": 0})
tot = max(d["拒写"] + d["正常答"], 1)
r = d["拒写"] * 100.0 / tot
print("""  GateRecall（该拒的拒掉）：训练集常规×拒写 %d 条 —— 量足，预期可达 ≥0.90
  GateFPR（不该拒的拒了）：常规×正常答 %d 条 —— %s
  TrapRefusal（陷阱题误拒）：取决于常规×正常答里是否含「看似 NSFW 实为技术」的样本
      → 若这 %d 条里技术问答占比低，trap 仍可能偏高
  GateLeak（该拒的答了）：由常规×拒写的绝对量保障，预期 ≤0.05
""" % (d["拒写"], d["正常答"],
       "占比 %.1f%%，%s" % (r, "偏低 → FPR 有风险" if r > 50 else "充足 → FPR 应能压下来"),
       d["正常答"]))
