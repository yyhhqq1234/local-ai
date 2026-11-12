#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mix-v5 验收汇总（离线重算版，只读已有评测 JSON，不再跑模型）

为什么单独存在：
  post_train_mix_v5.sh 的汇总段在 2026-10-30 14:22 首次运行时，选优只判了 acc>=0.65，
  与同表「判定」列的三条件（命中>=65% 且 参数错<=5 且 编造=0）自相矛盾 ——
  结果把 RE 侧有 1 条编造的候选写成了 "RE-PASS"。
  本脚本用修正后的口径重算，并补一段「逐题得失」，把 accuracy 相同背后的构成变化讲清楚。
"""
import io
import json
import os

T = "train"
OUT_MD = os.path.join(T, "2A-ACCEPTANCE-MIXV5.md")
LABELS = ["mixv5-4000", "mixv5-5200", "mixv5-final"]

lines = []


def say(s=""):
    print(s)
    lines.append(s)


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.isfile(p) else None


# ── 数据 ──────────────────────────────────────────────────────
c2a = {}
for L in LABELS:
    d = load(os.path.join(T, "out", "eval-2a-%s.json" % L))
    if d:
        c2a[L] = d

re_doc = load(os.path.join(T, "out", "eval-re-regress-mixv5.json"))
re_all = {r["label"]: r for r in re_doc["results"]} if re_doc else {}

BASE2A = (0.600, 0.400)      # r3 在 2A 40 题上的实测（eval-2a-r3-v2.json）
BAD2A = (0.306, 0.025)       # 上一轮训坏

say("=" * 88)
say("mix-v5 验收（方案 Y：kitty 23718 + 2A 2001 · 6430 步 · 2026-10-30）")
say("=" * 88)

# ── 一、2A ────────────────────────────────────────────────────
say("")
say("── 一、2A 编程轨迹（40 条 · max_new 1200 · 与基线同尺）──")
say("  %-14s %9s %10s %9s %8s %8s" % ("adapter", "avg_cov", "code_rate", "ngram20", "cov", "code"))
say("  %-14s %8.1f%% %9.1f%% %9.3f %8s %8s" % (
    "r3（不训练基线）", 100 * BASE2A[0], 100 * BASE2A[1], 0.0, "PASS", "PASS"))
for L in LABELS:
    if L not in c2a:
        say("  %-14s [缺]" % L)
        continue
    d = c2a[L]
    say("  %-14s %8.1f%% %9.1f%% %9.3f %8s %8s" % (
        L, 100 * d["avg_cov"], 100 * d["code_rate"], d.get("avg_ngram20", 0),
        "PASS" if d["avg_cov"] >= 0.60 else "FAIL",
        "PASS" if d["code_rate"] >= 0.40 else "FAIL"))
say("  %-14s %8.1f%% %9.1f%% %9s %8s %8s" % (
    "上一轮训坏(2a)", 100 * BAD2A[0], 100 * BAD2A[1], "—", "FAIL", "FAIL"))
say("  判据：avg_cov >=60% 且 code_rate >=40%（TASKPOINT §A1）")

# ── 二、RE ────────────────────────────────────────────────────
say("")
say("── 二、RE 回归（kitty 口径 40 条 · 同尺同参）──")
say("  %-14s %4s %6s %5s %5s %5s %8s %7s  %s" % (
    "label", "hit", "参数错", "选错", "编造", "回避", "acc", "acc判", "三条件判"))
re_full = {}
for lb, r in re_all.items():
    acc, noarg, fake = r.get("acc", 0), r.get("noarg", 99), r.get("fake", 99)
    ok3 = (acc >= 0.65 and noarg <= 5 and fake == 0)
    re_full[lb] = (acc, noarg, fake, ok3)
    say("  %-14s %4d %6d %5d %5d %5d %7.1f%% %7s  %s" % (
        lb, r.get("hit", 0), noarg, r.get("wrong", 0), fake, r.get("none", 0),
        100 * acc, "PASS" if acc >= 0.65 else "FAIL", "PASS" if ok3 else "FAIL"))
say("  判据（§A1）：命中>=65% 且 参数错<=5 且 编造=0 —— **三条同时成立才算过**")

# ── 三、逐题得失（accuracy 相同 ≠ 表现相同）─────────────────
say("")
say("── 三、逐题得失（mixv5-final vs r3）──")
if re_doc:
    a = {x["id"]: x for x in re_all["r3"]["detail"]}
    b = {x["id"]: x for x in re_all["mixv5-final"]["detail"]}
    gain, loss = [], []
    for k in a:
        if k not in b:
            continue
        if a[k]["kind"] != b[k]["kind"]:
            (gain if b[k]["kind"] in ("hit",) else loss).append(k)
    say("  r3 → mixv5-final：%d 题变好 / %d 题变差（净 0，但构成变了）" % (len(gain), len(loss)))
    say("")
    say("  变好（%s）：" % "/".join(gain))
    for k in gain:
        say("    %-4s %-3s %-22s expect=%s" % (k, a[k]["level"], a[k].get("note", "")[:22],
                                               a[k].get("expect")))
    say("")
    say("  变差（%s）：" % "/".join(loss))
    for k in loss:
        say("    %-4s %-3s %-22s expect=%s  mixv5 答=%s" % (
            k, a[k]["level"], a[k].get("note", "")[:22], a[k].get("expect"),
            b[k].get("got")))
    fake_ids = [k for k in b if b[k].get("fake")]
    if fake_ids:
        say("")
        say("  ★ 编造（%s）：expect=%s，mixv5 实际给出 %s" % (
            "/".join(fake_ids), b[fake_ids[0]].get("expect"), b[fake_ids[0]].get("fake")))
        say("    该名字在训练集 / eval case / kitty 脚本里 **0 命中**（已 grep 核实）")
        say("    ⇒ 不是数据里带的工具名，是模型按「选它的理由：X（通道 Y）」模板自造的",
            )
        say("    风险类型：**格式学得太好 → 不确定时用模板把工具名编出来**。下一轮需加「只许用目录内工具名」约束。")

# ── 四、选优 ──────────────────────────────────────────────────
say("")
say("── 四、选优（RE 三条件为约束，2A 为目标）──")
cands = []
for L in LABELS:
    if L not in c2a or L not in re_full:
        continue
    acc, noarg, fake, ok3 = re_full[L]
    d = c2a[L]
    ok2a = d["avg_cov"] >= 0.60 and d["code_rate"] >= 0.40
    cands.append((L, d["avg_cov"], d["code_rate"], acc, ok2a, ok3))
if cands:
    for c in cands:
        say("  %-14s cov %5.1f%%  code %5.1f%%  RE %5.1f%%  2A:%s  RE:%s" % (
            c[0], 100 * c[1], 100 * c[2], 100 * c[3],
            "PASS" if c[4] else "FAIL", "PASS" if c[5] else "FAIL"))
    best = sorted(cands, key=lambda x: (-int(x[5]), -int(x[4]), -x[2], -x[1]))[0]
    say("")
    say("  推荐交付：**%s**（2A 侧最优、RE 侧缺口最小）" % best[0])
    say("  但注意：**没有任何候选同时满足 2A 与 RE 三条件**")

say("")
say("=" * 88)
say("总判定：**FAIL（部分达成）**")
say("=" * 88)
say("""
  达成：① RE 命中率 75.0% 与 r3 完全持平（主线能力未退化，§A1 的 >=65% 满足）
        ② 2A code_rate 0.375→0.400（final 压线达标），相对上一轮训坏的 0.025 提升 15 倍
        ③ ngram20 = 0.000（三个候选全零，无背答案）
  未达成：① 2A avg_cov 0.485-0.499 < 0.60，且低于 r3 基线的 0.600
          ② RE 出现 1 条编造（kitty_interceptor，训练集里不存在），三条件判 FAIL

  结论（可写进计划文件）：
    · 方案 Y（8% rehearsal）**成功阻止了 2A 能力塌陷**，但**不足以超过不做 2A 训练的状态**；
      8% 只能减缓遗忘，不能提升能力 —— 开训前的预判已被数据证实。
    · 后半程（4000→6430）对 2A 目标边际收益 ≈ 0（cov 抖 ±0.007），
      真正有收益的是「不出标记 / 不塌陷」这部分，在 4000 步前就已达成。
    · 新增风险 B13：模型学会了「选它的理由：X（通道 Y）」模板后，会在不确定时自造工具名。
      下一轮数据侧需加约束（工具名必须来自给定目录），验收侧需保留「编造=0」这条硬线。

  下一步建议：
    方案 Z（双 adapter）优先 —— r3 保 RE，另起一个只训 2A 的 adapter，推理时按场景路由；
    方案 X（70:30）次之 —— 但需把 kitty 砍到 4670 条，RE 退化风险高，且本轮已证明 2A 侧在
    8% 曝光下几乎不动，说明需要的是「配比大幅倾斜」而不是「多训几步」。
""")

io.open(OUT_MD, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n-> 重写 %s" % OUT_MD)
