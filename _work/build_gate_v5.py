# -*- coding: utf-8 -*-
"""方案 C：按「内容」而不是「system 开关」重建 2B 门控训练集（v5）

核心思路（v2/v4b 的共同病根）：
  v2   → 常规组 100% 拒写 → 见 system 就拒（FPR .375 / trap 1.00）
  v4b  → 常规组 76.9% 拒写（v3 精确实测）→ 仍偏向拒，general/trap 会被误拒
  两者都让模型学成「看 system 决定」，而评测考的是「看 user 内容决定」

v5 的改造（四条）：
  ① 删 kitty 技术污染（635 行，正则命中且无 NSFW 标记）
  ② 给「无 system」的样本补 system：
       NSFW 正文/创作     → 许可
       知识/技术/翻译/学术 → 常规      ← 这是方案 C 的关键：常规模式下照答
  ③ 常规组的「该答」从 635 提到 ~1,500（把 ② 里判为知识的样本计入）
  ④ 常规组目标比例 拒:答 ≈ 1.4:1（评测是 1.2:1，留一点余量保 Recall）

用法：
  python _work/build_gate_v5.py              # dry-run，只看统计
  python _work/build_gate_v5.py --apply      # 落盘 train-2b-gated-v5.jsonl
"""
import argparse
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
L9B = "train/lines/9b-oxcoder"
SRC = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train-deleak.jsonl")
OUT = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v5.jsonl")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

SYS_PERMIT = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
SYS_NORMAL = "模式：常规（未授权成人向内容）。不含露骨性描写。"

STRICT_REFUSE = re.compile(
    r"(我不打算|我不写|这条超出|这条不(?:行|能)|先不生成|先停|先按一般向|按常规|"
    r"需要你(?:明确)?(?:标记|标注|显式)|需要(?:显式|明确)标记|补一个 ?NSFW|"
    r"没有开关|不带授权标记|不能默认|超出常规|降级成非露骨|非露骨版|描写收着)"
)
TECH = re.compile(r"kitty_[a-z_]+|OK\||ERR\||A ?通道|回包|桥侧|SYNC_|KM_|P_BACK|S_NEW|MODENUM|指针链|P_WALK")
# 露骨度计数（≥2 视为成人向正文）
SEX = re.compile(r"乳头|肉棒|龟头|淫|射精|高潮|肏|阴道|阴茎|乳房|阴蒂|精液|小穴|蜜穴|口交|抽插|胴体|肉便器|发情|潮吹")
# ★ 创作指令优先判定（上一版用全文 ASK 匹配，把「接着写下去…正文明明含『什么』」误判成知识问答，1534/7427=20.7%）
CREATE = re.compile(r"接着写|继续写|续写|往下推进|往下写|写下去|写一段|写正文|展开|扩写|重写|润色|"
                    r"推进|延续|改编|补写|生成正文|保持叙事|保持叙述|保持.{0,6}节奏|情节照推|"
                    r"改写成|改成|换成|转成|翻译成|用.{0,8}笔法|第三人称|第一人称|更露骨|更含蓄")
# ★ 只认「明确的问句/任务词」，去掉裸的 什么/怎么/如何/哪/是否
#   —— 裸词会在正文里大量命中（「我怎么…」「不想调情什么的」），是上一版 8.9% 误判的来源
ASK = re.compile(r"[?？]|翻译|简述|评价|分析|讲讲|说说|什么意思|"
                 r"怎么(?:写|做|办|理解|看|处理)|为什么(?:会|要|不)|"
                 r"合规|边界|标准|区别|依据|流程|步骤")
NARR = re.compile(r'^[\s　"「『“（(]')


def msgs(o):
    return o.get("messages") or []


def sys_of(o):
    return next((str(m.get("content", "")) for m in msgs(o) if m.get("role") == "system"), "")


def user_of(o):
    return "".join(str(m.get("content", "")) for m in msgs(o) if m.get("role") == "user")


def asst_of(o):
    return "".join(str(m.get("content", "")) for m in msgs(o) if m.get("role") == "assistant")


def is_refuse(a):
    head = (a or "").lstrip()[:80]
    if not head or NARR.match(head):
        return False
    return bool(STRICT_REFUSE.search(head))


# ★ 叙事前缀：出现即判定为「续写素材」，不论后面有没有问号
#   （「以下是故事的前文背景：…这是？」这类会骗过问句规则，是最后 5.7% 误判的主因）
STORY_PREFIX = re.compile(
    r"^\s*(以下是故事|故事进展|承接上文|把下面这段|把这段|根据这段|根据下面|按下面的场景|"
    r"用第三人称|用第一人称|延续同一|保持.{0,6}(?:节奏|密度|叙述)|接着|续写|往下|展开)")


def classify_content(u, a):
    """返回 ('创作请求'|'知识问答'|'正文'|'拒写降级', 依据)

    ★ 判定顺序（严格）：叙事前缀 → 创作动词 → 拒写降级 → 明确问句 → 高露骨 → 叙事
    """
    raw = (u or "").strip()
    instr = raw[:80]
    narrow = raw[:36]
    sex_u = len(SEX.findall(u))
    sex_a = len(SEX.findall(a))
    if STORY_PREFIX.search(instr):
        return "创作请求", "叙事前缀"
    if CREATE.search(instr):
        return "创作请求", "指令区含创作动词"
    if STRICT_REFUSE.search((a or "").lstrip()[:80]):
        return "拒写降级", "assistant 开场即拒"
    if ASK.search(narrow):
        return "知识问答", "指令区含明确问句/任务词"
    if sex_u >= 2 or sex_a >= 3:
        return "正文", "高露骨"
    return "正文", "叙事"


rows = []
dropped_tech = 0
n_in = 0
for line in io.open(SRC, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    n_in += 1
    o = json.loads(line)
    u, a = user_of(o), asst_of(o)
    # ① 删技术污染
    if TECH.search(u) and len(SEX.findall(u)) < 2:
        dropped_tech += 1
        continue
    rows.append(o)

print("=" * 92)
print("方案 C · v5 重建%s" % ("" if args.apply else "（dry-run）"))
print("=" * 92)
print("  源 %d 行 → 删技术污染 %d 行 → 保留 %d 行" % (n_in, dropped_tech, len(rows)))

# ②③ 重新判定 system 与 拒/答
out_rows = []
stat = defaultdict(lambda: {"拒": 0, "答": 0})
for o in rows:
    u, a = user_of(o), asst_of(o)
    old_sys = sys_of(o)
    refuse = is_refuse(a)
    kind, why = classify_content(u, a)
    # 补 system
    if "许可" in old_sys:
        new_sys = SYS_PERMIT
    elif "常规" in old_sys:
        new_sys = SYS_NORMAL
    else:
        # 无 system：按内容判
        new_sys = SYS_PERMIT if kind in ("创作请求", "正文") and not refuse else SYS_NORMAL
        if refuse:
            new_sys = SYS_NORMAL      # 拒写样本一律归常规（拒 = 未授权）
    new_msgs = [{"role": "system", "content": new_sys}] + \
               [{"role": m["role"], "content": m["content"]} for m in msgs(o) if m.get("role") != "system"]
    o2 = {"messages": new_msgs}
    out_rows.append(o2)
    sk = "许可" if "许可" in new_sys else "常规"
    stat[sk]["拒" if refuse else "答"] += 1

print()
print("  %-6s %8s %8s %8s %8s %s" % ("system", "拒", "答", "合计", "拒占比", "评测参照"))
print("  " + "-" * 70)
ev = {"许可": "on 30 全该答（拒应≈0）", "常规": "off 30 拒 / gen+trap 25 答 ⇒ 54.5%"}
for sk in ("许可", "常规"):
    d = stat[sk]
    tot = d["拒"] + d["答"]
    print("  %-6s %8d %8d %8d %7.1f%%  %s"
          % (sk, d["拒"], d["答"], tot, d["拒"] * 100.0 / max(tot, 1), ev[sk]))

d = stat["常规"]
tot = max(d["拒"] + d["答"], 1)
r = d["拒"] * 100.0 / tot
print()
print("  常规组拒占比 %.1f%%（目标 50~60%%）→ %s"
      % (r, "✅ 落在目标区间" if 45 <= r <= 65 else "⚠ 需要再调"))
print("  常规组「该答」样本 %d 条 —— 评测要考 25 条（gen 16 + trap 9），覆盖率 %.1fx"
      % (d["答"], d["答"] / 25.0))

# ④ 若常规组拒仍偏多，随机抽掉一部分拒写，把比例压到目标
TARGET_RATIO = 0.57            # 拒 / (拒+答)
if r > 65:
    keep_ans = d["答"]
    max_refuse = int(keep_ans * TARGET_RATIO / (1 - TARGET_RATIO))
    print()
    print("  ④ 需要从常规×拒里裁掉 %d 条（%d → %d）才能到 %.0f%%"
          % (d["拒"] - max_refuse, d["拒"], max_refuse, TARGET_RATIO * 100))
    need = d["拒"] - max_refuse
    kept, cut = [], 0
    import random
    rng = random.Random(42)
    idx_refuse = [i for i, o in enumerate(out_rows)
                  if SYS_NORMAL in sys_of(o) and is_refuse(asst_of(o))]
    rng.shuffle(idx_refuse)
    drop = set(idx_refuse[:need])
    out_rows = [o for i, o in enumerate(out_rows) if i not in drop]
    cut = len(drop)
    print("      已裁掉 %d 条 → 最终 %d 行" % (cut, len(out_rows)))

# 复算
final = defaultdict(lambda: {"拒": 0, "答": 0})
for o in out_rows:
    sk = "许可" if "许可" in sys_of(o) else "常规"
    final[sk]["拒" if is_refuse(asst_of(o)) else "答"] += 1
print()
print("  最终分布：")
for sk in ("许可", "常规"):
    d = final[sk]
    tot = d["拒"] + d["答"]
    print("    %-4s 拒 %5d / 答 %5d = %6.1f%% 拒" % (sk, d["拒"], d["答"], d["拒"] * 100.0 / max(tot, 1)))
print("    合计 %d 行（%d 步 @ ga4）" % (len(out_rows), len(out_rows) // 4))

if args.apply:
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for o in out_rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print()
    print("  → %s" % OUT)
else:
    print()
    print("  dry-run：未落盘。加 --apply 生成 %s" % os.path.basename(OUT))
