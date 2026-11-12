#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gate_neg2.py —— 负样本改为「拒绝句 + 150~250 字非露骨替代段」（不训练，只造数据）

依据（2026-11-02 三次评测）
  gen7-200 L1 0.750 → gen7-600 L1 0.188，空回复 23% → 41%，loss 还更低
  → 训练目标在奖励"少说话"：3,407 条负样本全是同一句短拒绝，模型的最省力解就是 EOS。

做法
  负样本 = ①原样保留统一拒绝句（门控判据靠它）
          ②追加 150–250 字「非露骨替代方向」：从同一条正样本正文里摘 1–2 句
            **不含敏感词**的句子（氛围/心理/情节），再用多变框架串起来
  约束
    · 与正样本共用同一 user prompt（配对 100% 保持）
    · 敏感词命中必须 0（judge_nsfw=False）
    · 总长 150–250 字；不含编排词（识别到/模式/拆解/可交付…）

用法：python build_gate_neg2.py --pos gen5-gate.jsonl --out gen8-gate.jsonl --ratio 2
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "train/lines/_shared/scripts"))
from nsfw_gate_eval import load_terms, judge_nsfw  # noqa: E402

POS_SYS = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
NEG_SYS = "模式：常规（未授权成人向内容）。不含露骨性描写。"
REFUSAL = "当前为常规模式（未授权成人向内容），不输出露骨性描写。"

ORCH = ("识别到", "先判断", "落点", "拆解", "可执行", "可交付", "同步进度", "模式：", "常规模式")
FRAMES = [
    "可以按这个口径继续：{a}。{b}把握氛围与人物心理即可，相关段落留白。",
    "换个写法：{a}；{b}重点放在情绪推进，不写身体细节。",
    "建议走非露骨版本：{a}。{b}保持叙事密度，细节用环境与心理承载。",
    "可以这样落笔：{a}，{b}把张力放在对话与停顿上，不做具体展开。",
    "非露骨版本可行：{a}；{b}情感线照旧推进，关键部分以省略处理。",
]
CLOSERS = ["在这条线里推进即可。", "按这个方向写不会越界。", "保持这个尺度就够。"]


TAIL_PAD = "如果还需要延展，可以补一段事后反应与旁人的态度变化，让情节自然往前走，不必回到显性描写。"
RAW_POOL = (
    "可以按这个口径继续：把镜头停在动作发生之前，用环境的声音、光线与温度铺陈，再让人物的犹豫和试探推动情节；对话保持原本的节奏，接触一笔带过，其余整段留白，这样既保住张力也不越界。",
    "换个写法：同一场景改成非露骨版本，重点写关系的变化——谁先让步、谁在遮掩、谁在权衡，把心理活动写透；原本的段落用时间跳跃替代，情节推进速度不变，只是把显性部分省略掉。",
    "建议走非露骨版本：保留情境、人物动机与冲突走向，用氛围和对话承载全部张力；关键时刻用一句留白收尾，比如灯熄了、门带上了，之后直接跳到次日清晨，读者的想象更有力。",
    "可以这样落笔：先把人物处境、代价和情绪写透，让读者明白这一步为什么非走不可；真正推进时点到为止，用一次停顿或视线交错代替，叙事密度和人物弧线都可以完整保留。",
)
GENERIC_POOL = tuple(x + TAIL_PAD for x in RAW_POOL)


def sentences(text, terms):
    sents = [s.strip() for s in re.split(r"(?<=[。！？…”』」])", text) if s and s.strip()]
    out = []
    for s in sents:
        if not (18 <= len(s) <= 130):
            continue
        # 单句必须「零命中」：judge_nsfw 是 ≥2 个不同词才判脏，
        # 含 1 个词的句子拼起来就会变成脏，所以这里按 hits==0 严筛
        if judge_nsfw(s, terms)[1] > 0:
            continue
        if any(w in s for w in ORCH):
            continue
        out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratio", type=float, default=2.0, help="pos 复本数（1 => 1:1）")
    ap.add_argument("--min-len", type=int, default=150)
    ap.add_argument("--max-len", type=int, default=250)
    a = ap.parse_args()

    terms = load_terms()
    st = collections.Counter()
    pos_rows, neg_rows = [], []
    seen = set()
    fi = 0

    for line in open(a.pos, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        msgs = r["messages"]
        sysm = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if "NSFW" not in sysm:
            continue
        user = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
        asst = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant").strip()
        if not user.strip() or not asst:
            st["pos_bad"] += 1
            continue
        if any(w in asst[:200] for w in ORCH):
            st["pos_orch"] += 1
            continue
        h = hashlib.blake2b(user.encode(), digest_size=8).hexdigest()
        if h in seen:
            st["pos_dup"] += 1
            continue
        seen.add(h)
        pos_rows.append({"messages": [{"role": "system", "content": POS_SYS},
                                      {"role": "user", "content": user},
                                      {"role": "assistant", "content": asst}],
                         "tools": None, "meta": {"cat": "cont"}})

        # 组非露骨替代段
        sents = sentences(asst, terms)
        if not sents:
            # 正样本整段都是露骨内容 → 没有可摘的干净句，用多变通用替代方案（不引用原文）
            generic = [
                "可以按这个口径继续：把镜头停在动作发生之前，用环境的声音、光线与温度铺陈，再让人物的犹豫和试探推动情节；对话保持原本的节奏和火气，身体接触一笔带过，性描写整段留白。这样既保住张力，也不越出常规模式的范围。",
                "换个写法：同一场景改成非露骨版本，重点写关系的变化——谁先让步、谁在遮掩、谁在权衡，把心理活动写透；原本的身体段落用时间跳跃或门关上的那一刻替代，情节推进速度不变，只是把显性部分省略掉。",
                "建议走非露骨版本：保留情境、人物动机与冲突的走向，用氛围和对话承载全部张力；关键时刻用一句留白收尾，比如灯熄了、门带上了，之后直接跳到次日清晨，读者的想象比直接描写更有力。",
                "可以这样落笔：先把人物处境、代价和情绪写透，让读者明白这一步为什么非走不可；真正推进时点到为止，用动作前的一句停顿或视线交错代替，不做具体展开。叙事密度和人物弧线都可以完整保留。",
            ]
            body = generic[fi % len(generic)]
            neg_rows.append({"messages": [{"role": "system", "content": NEG_SYS},
                                          {"role": "user", "content": user},
                                          {"role": "assistant",
                                           "content": REFUSAL + "\n\n" + body}],
                             "tools": None, "meta": {"cat": "scene"}})
            st["neg_generic"] += 1
            fi += 1
            continue
        # 逐句累加，凑进 [min_len, max_len]（长度只算 body，拒绝句是固定项）
        lo = max(80, a.min_len)
        hi = max(lo + 10, a.max_len)
        body = ""
        acc = []
        for k in range(len(sents)):
            acc.append(sents[k].rstrip("。"))
            head = "可以按这个口径继续：%s。" % "，".join(acc)
            cand = head + CLOSERS[fi % len(CLOSERS)]
            if lo <= len(cand) <= hi:
                body = cand
                break
            if len(cand) > hi:
                acc.pop()
                break
        if not body and acc:
            cand = "可以按这个口径继续：%s。%s" % ("，".join(acc), CLOSERS[fi % len(CLOSERS)])
            if len(cand) <= hi + 40:
                body = cand
        if not body:
            st["neg_skip_len"] += 1
            continue
        fi += 1
        # 只检 body；仍命中的话一律换成通用模板（保证 0 敏感词，不再丢行）
        if judge_nsfw(body, terms)[0]:
            body = GENERIC_POOL[fi % len(GENERIC_POOL)]
            st["neg_fallback_generic"] += 1
        content = REFUSAL + "\n\n" + body
        neg_rows.append({"messages": [{"role": "system", "content": NEG_SYS},
                                      {"role": "user", "content": user},
                                      {"role": "assistant", "content": content}],
                         "tools": None, "meta": {"cat": "scene"}})

    # ── 统一长度整形：拒绝句 + 替代段，总长压进 [min_len, max_len] ──
    PAD = (
        "如果篇幅不够，可以补一段场面调度：谁站在哪、光从哪里来、屋里有什么声音，用这些把节奏垫起来。",
        "也可以把人物此刻的迟疑写细：想说没说的话、想起的旧事、手停在半空的瞬间，都属于可写的部分。",
        "需要更多字数时，写事后反应：旁人的态度变化、约定怎么落地、下一次见面如何开口，都能自然延长。",
        "还可以在开头加一句时间地点交代，结尾留一个悬念动作，让读者知道事情还没完，尺度不必向前推。",
    )
    for r in neg_rows:
        c = r["messages"][2]["content"]
        k = 0
        while a.min_len + len(REFUSAL) + 2 > len(c) and k < 4:
            c = c + PAD[(hash(c) + k) % len(PAD)]
            k += 1
        if a.max_len < len(c):
            cut = c.rfind("。", 0, a.max_len)
            c = c[:cut + 1] if cut > a.min_len else c[:a.max_len]
        # 整形后复检：补 PAD 可能引入敏感词 → 命中就换通用模板（不放宽规格）
        if judge_nsfw(c[len(REFUSAL):], terms)[0]:
            c = REFUSAL + "\n\n" + GENERIC_POOL[(k + 1) % len(GENERIC_POOL)]
        r["messages"][2]["content"] = c

    reps = max(1, int(round(a.ratio)))
    out = pos_rows * reps + neg_rows
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    hh = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            hh.update(c)

    pu = {r["messages"][1]["content"] for r in pos_rows}
    nu = {r["messages"][1]["content"] for r in neg_rows}
    lens = [len(r["messages"][2]["content"]) for r in neg_rows]
    lens.sort()
    print(f"[out] {a.out}  {len(out)} 行  sha {hh.hexdigest()[:16]}")
    print(f"[pair] pos {len(pu)} / neg {len(nu)} / 交集 {len(pu & nu)} "
          f"= {len(pu & nu)/max(1,len(pu))*100:.1f}%")
    print(f"[ratio] pos {len(pos_rows)*reps} : neg {len(neg_rows)}")
    if lens:
        print(f"[len] 负样本长度 p10={lens[len(lens)//10]} p50={lens[len(lens)//2]} "
              f"p90={lens[int(len(lens)*0.9)]} min={lens[0]} max={lens[-1]}")
    print(f"[stat] {dict(st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
