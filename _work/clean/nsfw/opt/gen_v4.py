# -*- coding: utf-8 -*-
"""gen_v4.py — NSFW v4 三件套（零起点加强 / 续写加强 / 前置指令）生成器。

设计依据（b1v3 实测，2026-11-21）
--------------------------------
· 零起点固定 20 prompt 仅 11/20 = 55%（目标 70%）；同一模型对部分 prompt 一次
  给 60–75 个露骨词、对另一些给 0 词 → 方差来自「开场结构」，不是能力缺失。
  对策①：只取前 300 字已有 ≥3 个 strict 词的正文（ctx768 截断后仍吃得到露骨内容）。
  对策②：一半 user 写成显式结构指令（「开头 100 字内就进入身体描写」）。
· 续写回归 1/3（上一版 2/3）→ 零起点样本把「先有前文」的条件挤掉。
  对策：独立续写集，user 必带 80–200 字原文开头（开头本身 ≥2 strict 词），
        assistant 只给后续（只切分，不改字）。
· 452 步 × 6144 = 2.746M token（比预估少 34%）→ 数据要「密」：A/C 只取前段密集正文。

产物（写 cleaned/opt/；旧文件保留）
-----------------------------------
  nsfw-zeroshot-v4.jsonl   1800 行
  nsfw-continue-v4.jsonl   1400 行
  nsfw-frontload-v4.jsonl   400 行
  _work/clean/nsfw/opt/v4-stats.json
  _work/clean/nsfw/opt/v4-dedup.json
  _work/clean/nsfw/opt/report-v4.md（report_v4.py 生成）

去重口径：same assistant 正文只出现在一份里（优先 A > B > C）。
  B 的 assistant 是切分后的「后续」，与 A 的整篇正文不是同一段文本；
  当密集正文总量不足以同时满足 1800+1400 时，B 允许复用 A 的源正文（assistant
  仍不同），复用行在 ledger 里标 reuse_from_a=true 并给出比例。

可复现：SEED 固定；候选按 sha256(归一化正文) 排序，无随机数。

用法
----
  python _work/clean/nsfw/opt/gen_v4.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opt_common as C  # noqa: E402

SEED = 20261121
ROOT = C.ROOT
DATA = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data")
SRC_FILES = [
    os.path.join(DATA, "nsfw-gated", "cleaned", "nsfw-clean.jsonl"),
    os.path.join(DATA, "nsfw-gated", "gate-pos.jsonl"),
    os.path.join(DATA, "nsfw-gated", "train-2b-gated-v5.jsonl"),
]
OLD_ZERO = os.path.join(C.OUT_DIR, "nsfw-zeroshot.jsonl")

TARGET_A, TARGET_B, TARGET_C = 1800, 1400, 400
FRONT_A = 300
FRONT_MIN = 3
PREFIX_RANGE = (80, 200)
PREFIX_STRICT_MIN = 2
SUFFIX_MIN = 200
BODY_MIN, BODY_MAX = 300, 6000

SENT_RE = re.compile(r"[。！？；\n]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
CONT_HEAD = re.compile(r"^[\s　…—「『\"'（(]{0,6}(接着|继续|上文|前述|刚才|前文|接上|续写|后面)")
TRUNC = ["中段省略", "此处省略", "（略）", "(略)", "略去", "……继续", "（下略）", "下文省略"]
META = ["我需要一个", "显式开关", "骨架", "无法生成", "不能写", "换个话题", "非露骨",
        "替代方案", "作为AI", "作为 AI", "抱歉", "我理解你想"]
CODE_MARK = ["```", "Traceback", "def ", "import ", "/workspace/", "ValueError"]
PSYCH = ["心想", "心里", "思绪", "回忆", "想起", "情绪", "内心", "感觉自",
         "她觉得自己", "他觉得自己", "不由得想", "脑海中", "意识里"]
# 成年语境豁免：这些词本身即成人场景（大学/已婚/夫妻/职场），不构成未成年指向
ADULT_CTX = ["大学", "学院", "研究生", "已婚", "丈夫", "妻子", "夫妻", "结婚",
             "老公", "老婆", "离婚", "职场", "公司", "办公室", "上司", "同事",
             "出差", "结婚证", "婚房", "阿姨", "人妻", "寡妇", "成年"]

# 成年声明（SOFT 词必需；后置追加，不动正文开头——A 的「开头就进」不能被打断）
ADULT_DECL = "\n\n（说明：本篇角色均为成年人，年龄均已满18岁。）"
# 学段身份词：声明无法豁免（与正文自相矛盾），直接弃
STAGE_MINOR = ["JK", "女高中生", "高中生", "初中生", "小学生", "中学生", "学生妹"]

# ---------------------------------------------------------------- user 模板

A_EXPLICIT_NUM = [
    "[[NSFW]] 开头 100 字内就进入身体描写，不要铺垫，{n} 字以上。",
    "[[NSFW]] 前 100 字必须出现具体的身体接触与性行为描写，别写心理和环境，{n} 字以上。",
]
A_EXPLICIT_GEN = [
    "[[NSFW]] 第一段就进入性行为，不要开场白、不要气氛铺垫，{n} 字以上。",
    "[[NSFW]] 直接从身体接触写起，越具体越好，别用隐喻带过，{n} 字以上。",
    "[[NSFW]] 开头就写身体，不要前情提要，写到结束不要收着，{n} 字以上。",
]
A_PLAIN = [
    "[[NSFW]] 写个场景，题材随你，直接正文，{n} 字以上。",
    "[[NSFW]] 直接写一段成人向正文，从零开始，不要前情提要，{n} 字以上。",
    "[[NSFW]] 给我写一段露骨的成人向情节，从零开始，不要铺垫，{n} 字左右。",
    "[[NSFW]] 不限题材，直接写一段露骨的正文，{n} 字以上，别用省略号带过。",
    "[[NSFW]] 从零写一段成人向情节，直接进入正文，{n} 字以上。",
]

B_TMPL = [
    "根据这段开头接着写，保持叙述连贯：\n\n{pre}",
    "接着这段往下写，别重开：\n\n{pre}",
    "续写下面这段，保持人称和节奏：\n\n{pre}",
    "别重新开头，直接从这段后面继续：\n\n{pre}",
    "往下写，衔接上文：\n\n{pre}",
]

C_TMPL = [
    "[[NSFW]] 不要心理描写，只写身体与反应，直接开始。",
    "[[NSFW]] 跳过所有铺垫和心理活动，只写身体接触与生理反应，立刻开始，不要收着。",
    "[[NSFW]] 直接写，不要解释、不要旁白、不要心理独白，只保留动作和身体反应。",
    "[[NSFW]] 从第一句就进入行为，禁止写情绪和回忆，只写身体。",
    "[[NSFW]] 不许写心理，不许写环境，只写两个身体怎么动、什么反应，现在开始。",
    "[[NSFW]] 只写肉体，不写心，直接开始，越具体越好。",
]


def sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def cjk_ratio(t: str) -> float:
    body = [c for c in t if not c.isspace()]
    return len(CJK_RE.findall(t)) / float(len(body)) if body else 0.0


def strict_distinct(t: str) -> int:
    return sum(1 for w in C.STRICT_TERMS if w in t)


def cut_of(body: str):
    best = None
    for m in SENT_RE.finditer(body):
        p = m.end()
        if p < PREFIX_RANGE[0]:
            continue
        if p > PREFIX_RANGE[1]:
            break
        pre = body[:p]
        if C.strict_count(pre) >= PREFIX_STRICT_MIN and len(body) - p >= SUFFIX_MIN:
            best = p
    return best


def reject(body: str):
    if len(body) < BODY_MIN:
        return "too_short"
    if len(body) > BODY_MAX:
        return "too_long"
    if cjk_ratio(body) < 0.55:
        return "not_chinese"
    if CONT_HEAD.search(body):
        return "continuation_head"
    if any(w in body for w in TRUNC):
        return "truncated"
    if any(w in body for w in META):
        return "meta_or_refusal"
    if any(w in body for w in CODE_MARK):
        return "code_pollution"
    if C.common.refusal_hit(body):
        return "refusal_cue"
    if C.common.template_hit(body):
        return "template_cue"
    return None


def load_pool():
    pool = OrderedDict()
    per_src = Counter()
    dup = 0
    for p in SRC_FILES:
        if not os.path.exists(p):
            print("[warn] miss %s" % p)
            continue
        base = os.path.basename(p)
        with io.open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if C.common.branch_of(row) != "permit":
                    continue
                sysm = C.system_of(row)
                if sysm and sysm != C.SYS_PERMIT:
                    continue
                body = C.assistant_of(row).strip()
                if not body:
                    continue
                k = C.common.norm_text(body)
                if not k:
                    continue
                if k in pool:
                    dup += 1
                    continue
                pool[k] = {"body": body, "src": base}
                per_src[base] += 1
    return list(pool.values()), per_src, dup


def load_old_zero():
    out = []
    with io.open(OLD_ZERO, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line)["messages"][-1]["content"])
    return out


def stat_block(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return {}
    return {
        "n": n,
        "mean": C.fmt(sum(s) / float(n)),
        "median": s[n // 2],
        "p90": s[int(n * 0.9)],
        "min": s[0],
        "max": s[-1],
        "ge3_ratio": C.fmt(sum(1 for x in s if x >= 3) / float(n)),
        "ge5_ratio": C.fmt(sum(1 for x in s if x >= 5) / float(n)),
    }


def n_words(body: str) -> int:
    return max(400, min(1500, (len(body) // 100) * 100))


def build_candidates(pool):
    rej = Counter()
    out = []
    for it in pool:
        body = it["body"]
        tag = reject(body)
        if tag:
            rej[tag] += 1
            continue
        hit, reason = C.common.minor_hit(body)
        if hit:
            rej["minor_hard"] += 1
            continue
        needs_decl = False
        if C.common.soft_hits(body) and not C.common.has_adult_decl(body):
            if any(w in body for w in STAGE_MINOR):
                rej["minor_stage"] += 1
                continue
            if not any(w in body for w in ADULT_CTX):   # 成年语境直接放行，不加声明
                body = body + ADULT_DECL
                needs_decl = True
        if C.degen_codes(body)[0]:
            rej["degenerate"] += 1
            continue
        k = hashlib.sha256(C.common.norm_text(it["body"]).encode("utf-8")).hexdigest()[:16]
        out.append({
            "key": k,
            "body": body,
            "src": it["src"],
            "needs_decl": needs_decl,
            "f3": C.strict_count(body[:FRONT_A]),
            "f3d": strict_distinct(body[:FRONT_A]),
            "f100": C.strict_count(body[:100]),
            "cut": cut_of(body),
            "psych": sum(body.count(w) for w in PSYCH),
            "action": C.common.has_action(body),
            "strict": C.strict_count(body),
            "len": len(body),
        })
    return out, rej


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pool, per_src, dup = load_pool()
    old_bodies = load_old_zero()
    old_norm = {C.common.norm_text(b) for b in old_bodies}
    cands, rej = build_candidates(pool)
    for c in cands:
        c["old"] = c["body"] in old_norm or C.common.norm_text(c["body"]) in old_norm
    fresh = [c for c in cands if not c["old"]]
    cands.sort(key=lambda c: c["key"])
    fresh.sort(key=lambda c: c["key"])
    print("[pool] unique=%d src=%s cross_dup=%d usable=%d fresh=%d old800=%d"
          % (len(pool), dict(per_src), dup, len(cands), len(fresh), len(old_bodies)))
    print("[reject] %s" % dict(rej))

    # ---------------- A：零起点 1800（前 300 字 ≥3 strict，distinct ≥2） ----------------
    # 先分 A：decl 需求总下限 = 1800 − 非注入密集正文数，把注入尽量压在 B/C
    a_pool = [c for c in fresh if c["f3"] >= FRONT_MIN and c["f3d"] >= 2]
    a_pool.sort(key=lambda c: (c["needs_decl"], c["f3"], c["key"]))
    A = a_pool[:TARGET_A]
    a_keys = {c["key"] for c in A}

    # ---------------- B：续写 1400（切点 80–200 字、开头 ≥2 strict） ----------------
    stream = []
    stream += [c for c in fresh if c["cut"] and c["key"] not in a_keys]
    stream += [c for c in cands if c["old"] and c["cut"] and c["key"] not in a_keys]
    stream += [c for c in A if c["cut"]]          # 复用：assistant 是「后续」，与 A 不同文
    stream.sort(key=lambda c: (c["key"] in a_keys, c["needs_decl"], c["key"]))
    B, seen_suf = [], set()
    for c in stream:
        if len(B) >= TARGET_B:
            break
        suf = c["body"][c["cut"]:]
        k = C.common.norm_text(suf)
        if k in seen_suf:
            continue
        seen_suf.add(k)
        B.append(c)
    b_keys = {c["key"] for c in B}

    # ---------------- C：前置指令 400（前段最密 + 身体动作多 + 心理少） ----------------
    # 密集正文已被 A/B 用尽，C 从「B 的源正文」取整篇（B 的 assistant 是后续，文本不同）
    used = a_keys | b_keys
    c_pool = [c for c in fresh if c["key"] not in used
              and c["f3"] >= 4 and c["action"] and c["psych"] <= 2]
    if len(c_pool) < TARGET_C:
        c_pool += [c for c in fresh if c["key"] not in used
                   and c["f3"] >= FRONT_MIN and c["action"]
                   and c["key"] not in {x["key"] for x in c_pool}]
    if len(c_pool) < TARGET_C:                       # 扩到 B 源正文（exclude A / 老集）
        extra = [c for c in B if c["key"] not in a_keys and not c["old"]
                 and c["f3"] >= FRONT_MIN
                 and c["key"] not in {x["key"] for x in c_pool}]
        extra.sort(key=lambda c: (not (c["f3"] >= 4 and c["action"] and c["psych"] <= 2),
                                  c["needs_decl"], -c["f3"], c["key"]))
        c_pool += extra
    c_pool.sort(key=lambda c: (c["needs_decl"], -c["f3"], c["key"]))
    Cset = c_pool[:TARGET_C]
    b_reuse = sum(1 for c in B if c["key"] in a_keys)
    print("[pick] A=%d (decl=%d) B=%d (reuse_from_A=%d) C=%d"
          % (len(A), sum(1 for c in A if c["needs_decl"]), len(B), b_reuse, len(Cset)))

    # ---------------- 组装 ----------------
    out_a, out_b, out_c = [], [], []
    tmpl_a, tmpl_b, tmpl_c = Counter(), Counter(), Counter()

    for i, c in enumerate(A):
        n = n_words(c["body"])
        if i % 2 == 0:
            if c["f100"] >= 2:
                t = A_EXPLICIT_NUM[(i // 2) % len(A_EXPLICIT_NUM)]
            else:
                t = A_EXPLICIT_GEN[(i // 2) % len(A_EXPLICIT_GEN)]
            kind = "explicit"
        else:
            t = A_PLAIN[(i // 2) % len(A_PLAIN)]
            kind = "plain"
        tmpl_a[t] += 1
        out_a.append({"messages": [
            {"role": "system", "content": C.SYS_PERMIT},
            {"role": "user", "content": t.format(n=n)},
            {"role": "assistant", "content": c["body"]},
        ], "_key": c["key"], "_src": c["src"], "_kind": kind,
            "_decl": c["needs_decl"], "_reuse": False})

    for i, c in enumerate(B):
        p = c["cut"]
        pre, suf = c["body"][:p], c["body"][p:]
        t = B_TMPL[i % len(B_TMPL)]
        tmpl_b[t] += 1
        out_b.append({"messages": [
            {"role": "system", "content": C.SYS_PERMIT},
            {"role": "user", "content": t.format(pre=pre)},
            {"role": "assistant", "content": suf},
        ], "_key": c["key"], "_src": c["src"], "_decl": c["needs_decl"],
            "_reuse": c["key"] in a_keys, "_pre_len": len(pre),
            "_pre_strict": C.strict_count(pre)})

    for i, c in enumerate(Cset):
        t = C_TMPL[i % len(C_TMPL)]
        tmpl_c[t] += 1
        out_c.append({"messages": [
            {"role": "system", "content": C.SYS_PERMIT},
            {"role": "user", "content": t},
            {"role": "assistant", "content": c["body"]},
        ], "_key": c["key"], "_src": c["src"], "_decl": c["needs_decl"], "_reuse": False})

    # ---------------- 统计 ----------------
    def bodies_of(rows):
        return [r["messages"][-1]["content"] for r in rows]

    def overlap_old(rows):
        bs = bodies_of(rows)
        hit = sum(1 for b in bs if C.common.norm_text(b) in old_norm)
        return hit, (C.fmt(hit / float(len(bs))) if bs else 0.0)

    stats = {
        "generated_at": "2026-11-21",
        "seed": SEED,
        "design": {
            "front_window": FRONT_A, "front_min_strict": FRONT_MIN,
            "prefix_range": list(PREFIX_RANGE),
            "prefix_strict_min": PREFIX_STRICT_MIN, "suffix_min": SUFFIX_MIN,
            "targets": {"A": TARGET_A, "B": TARGET_B, "C": TARGET_C},
            "sources": [os.path.relpath(p, ROOT) for p in SRC_FILES],
        },
        "pool": {"unique_bodies": len(pool), "by_src": dict(per_src),
                 "cross_src_dup": dup, "usable": len(cands),
                 "fresh": len(fresh), "reject": dict(rej)},
        "files": {},
        "user_templates": {
            "A_counts": {"%02d" % i: v for i, (_, v) in enumerate(
                sorted(tmpl_a.items(), key=lambda kv: -kv[1]))},
            "B_counts": {"%02d" % i: v for i, (_, v) in enumerate(
                sorted(tmpl_b.items(), key=lambda kv: -kv[1]))},
            "C_counts": {"%02d" % i: v for i, (_, v) in enumerate(
                sorted(tmpl_c.items(), key=lambda kv: -kv[1]))},
            "A_explicit_ratio": C.fmt(sum(1 for r in out_a if r["_kind"] == "explicit")
                                      / float(len(out_a))),
            "A_distinct_shapes": len(tmpl_a),
            "B_distinct_shapes": len(tmpl_b),
            "C_distinct_shapes": len(tmpl_c),
        },
    }

    specs = [("A", out_a, "nsfw-zeroshot-v4.jsonl"),
             ("B", out_b, "nsfw-continue-v4.jsonl"),
             ("C", out_c, "nsfw-frontload-v4.jsonl")]
    for name, rows, fname in specs:
        bs = bodies_of(rows)
        ov_hit, ov_rate = overlap_old(rows)
        block = {
            "path": os.path.join(C.OUT_DIR, fname),
            "rows": len(rows),
            "unique_assistant": len(set(bs)),
            "unique_assistant_norm": len({C.common.norm_text(b) for b in bs}),
            "front300_strict": stat_block([C.strict_count(b[:FRONT_A]) for b in bs]),
            "overlap_old800": {"n": ov_hit, "rate": ov_rate},
            "len": stat_block([len(b) for b in bs]),
            "src": dict(Counter(r["_src"] for r in rows)),
            "adult_decl_appended": sum(1 for r in rows if r["_decl"]),
            "reuse_source_from_a": sum(1 for r in rows if r["_reuse"]),
        }
        if name == "A":
            block["front100_ge2_ratio"] = C.fmt(
                sum(1 for b in bs if C.strict_count(b[:100]) >= 2) / float(len(bs)))
            block["strict_total"] = stat_block([C.strict_count(b) for b in bs])
        if name == "B":
            block["prefix_len"] = stat_block([r["_pre_len"] for r in rows])
            block["prefix_strict"] = stat_block([r["_pre_strict"] for r in rows])
            block["prefix_ge2_ratio"] = C.fmt(
                sum(1 for r in rows if r["_pre_strict"] >= 2) / float(len(rows)))
        if name == "C":
            block["front300_ge4_ratio"] = C.fmt(
                sum(1 for b in bs if C.strict_count(b[:FRONT_A]) >= 4) / float(len(bs)))
        stats["files"][name] = block

    ledger = {"note": "same assistant 正文只出现在一份；优先 A > B > C；"
                      "B 的 reuse_from_a 表示源正文与 A 相同但 assistant 为切分后的后续。",
              "counts": {}, "rows": []}
    for name, rows, fname in specs:
        for r in rows:
            ledger["rows"].append({
                "sha16": r["_key"], "file": name, "src": r["_src"],
                "assistant_chars": len(r["messages"][-1]["content"]),
                "adult_decl": bool(r["_decl"]), "reuse_from_a": bool(r["_reuse"]),
            })
        ledger["counts"][name] = len(rows)
    ledger["counts"]["total"] = sum(len(x) for x in (out_a, out_b, out_c))
    ledger["unique_source_bodies"] = len({x["sha16"] for x in ledger["rows"]})

    if not args.dry_run:
        for name, rows, fname in specs:
            C.write_jsonl(os.path.join(C.OUT_DIR, fname),
                          [{"messages": r["messages"]} for r in rows])
        C.write_json(os.path.join(C.WORK, "v4-stats.json"), stats)
        C.write_json(os.path.join(C.WORK, "v4-dedup.json"), ledger)
    for name, rows, fname in specs:
        b = stats["files"][name]
        print("[out] %-26s rows=%d uniq=%d front300_med=%s ge3=%s decl=%d reuse=%d old_ov=%s"
              % (fname, b["rows"], b["unique_assistant"],
                 b["front300_strict"].get("median"), b["front300_strict"].get("ge3_ratio"),
                 b["adult_decl_appended"], b["reuse_source_from_a"],
                 b["overlap_old800"]["rate"]))


if __name__ == "__main__":
    main()
