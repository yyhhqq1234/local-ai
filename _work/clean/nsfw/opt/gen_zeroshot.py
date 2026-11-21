# -*- coding: utf-8 -*-
"""gen_zeroshot.py — 从 permit 正文生成「零起点」训练样本。

思路
----
现有 permit 行几乎都是「续写 / 改写」形态：user 里带一段露骨开头，assistant 接着写。
模型因此学到「先有前文才写正文」，零起点 prompt 只会退回暧昧言情。

本脚本不改写正文，只做 **任务形态变换**：同一段露骨正文，配一个「从零开始写」
的 user，要求模型在没有前文的情况下直接产出该正文。system 逐字沿用原集。

输出
----
train/lines/9b-oxcoder/data/nsfw-gated/cleaned/opt/nsfw-zeroshot.jsonl
_work/clean/nsfw/opt/zeroshot-stats.json

可复现
------
固定 random.seed(SEED)；排序 / 去重 / 抽样全部确定性。

用法
----
  python _work/clean/nsfw/opt/gen_zeroshot.py [--target 800] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import zlib
from collections import Counter, OrderedDict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opt_common as C

# ---------------------------------------------------------------- 参数

MIN_STRICT = 5          # 正文露骨词下限（strict 词表）
BODY_LEN = (400, 3000)  # 正文长度窗口（训练友好）
NEAR_DUP_JACCARD = 0.85
DEFAULT_TARGET = 800

SCENE_CAPS = OrderedDict([
    ("通用", 320), ("室内", 190), ("都市", 130), ("校园", 80),
    ("职场", 90), ("幻想", 70), ("户外", 60),
])

N_WORDS = [600, 800, 1000, 1200]

# 学段身份词：出现即视为未成年指向（中国学制下 高中/初中/小学 均在 18 岁以内），
# 不做「成年人声明」豁免——声明与正文自相矛盾，直接弃。
STAGE_MINOR = ["高中生", "初中生", "小学生", "中学生", "女高中生", "学生妹", "JK",
               "高一生", "高二生", "高三生", "初一", "初二", "初三"]
# 校园题材的成年声明（正文级；缺则注入，不改动正文其余部分）
ADULT_DECL_LINE = "（说明：本篇所有角色均为成年人，年龄均已满18岁。）\n\n"

# 零起点 prompt 模板：{head}=触发词+题材提示；{n}=字数要求
TEMPLATES = [
    "{head}直接写一段成人向正文，从零开始，不要前情提要，{n} 字以上。",
    "{head}写个场景，题材随你，直接正文，{n} 字以上。",
    "{head}给我写一段露骨的成人向情节，从零开始，不要铺垫，{n} 字左右。",
    "{head}写一段成人向的故事，从零起手，直接正文，{n} 字以上，不要省略。",
    "{head}不限题材，直接写一段露骨的正文，{n} 字以上，别用省略号带过。",
    "{head}从零写一段成人向情节，直接进入正文，{n} 字以上。",
]

# ---- 反例过滤 ---------------------------------------------------------
# 正文开头若带「接着上文」类衔接词，零起点下会显得突兀
CONT_HEAD = re.compile(r"^[\s　…—「『\"'（(]{0,6}(接着|继续|上文|前述|刚才|前文|接上|续写|后面)")
# 截断 / 省略痕迹（教模型跳写）
TRUNC = ["中段省略", "此处省略", "（略）", "(略)", "略去", "……继续", "（下略）", "下文省略"]
# 元话语 / 拒答 / 说明体
META = ["我需要一个", "显式开关", "骨架", "无法生成", "不能写", "换个话题", "非露骨",
        "替代方案", "作为AI", "作为 AI", "抱歉", "我理解你想"]
# 代码 / 日志污染
CODE_MARK = ["```", "Traceback", "def ", "import ", "/workspace/", "ValueError"]

CJK = re.compile(r"[\u4e00-\u9fff]")


def cjk_ratio(t: str) -> float:
    body = [c for c in t if not c.isspace()]
    if not body:
        return 0.0
    return len(CJK.findall(t)) / float(len(body))


def reject_reason(body: str):
    """返回拒绝原因码；None 表示通过。"""
    n = len(body)
    if n < BODY_LEN[0]:
        return "too_short"
    if n > BODY_LEN[1]:
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
    if C.strict_count(body) < MIN_STRICT:
        return "too_mild"
    if C.common.refusal_hit(body):
        return "refusal_cue"
    if C.common.template_hit(body):
        return "template_cue"
    return None


def minor_gate(body: str):
    """未成年红线：HARD 直接弃；SOFT 需正文自带成年声明。"""
    hit, reason = C.common.minor_hit(body)
    if hit:
        return "minor_hard:" + reason
    if C.common.soft_hits(body) and not C.common.has_adult_decl(body):
        return "minor_soft_no_decl"
    return None


def build_head(scene: str, adult_note: bool) -> str:
    parts = [C.TRIGGER]
    if scene != "通用":
        parts.append("题材：%s。" % scene)
    if adult_note:
        parts.append("角色均为成年人。")
    return " ".join(parts) + " "


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = C.load_rows()
    permit = C.permit_rows(rows)
    print("[in] rows=%d permit=%d" % (len(rows), len(permit)))

    rej = Counter()
    degen_detail = Counter()
    cands = []
    for i, r in enumerate(permit):
        body = C.assistant_of(r).lstrip(" \u3000\t\r\n")   # 只去开头空白，不改正文
        sysmsg = C.system_of(r)
        if sysmsg != C.SYS_PERMIT:       # 极端情形：system 不标准 → 不参与
            rej["sys_mismatch"] += 1
            continue
        rj = reject_reason(body)
        if rj:
            rej[rj] += 1
            continue
        scene = C.scene_label(body)
        adult_injected = False
        if scene == "校园":
            # 学段身份词 → 直接弃（成年人声明不能豁免「高中生」这类自相矛盾）
            if any(w in body for w in STAGE_MINOR):
                rej["campus_stage_minor"] += 1
                continue
            # 校园题材：正文必须明确声明全员成年；缺则注入一行声明（不改正文其余部分）
            if not C.common.has_adult_decl(body):
                body = ADULT_DECL_LINE + body
                adult_injected = True
        rj = minor_gate(body)
        if rj:
            rej[rj.split(":")[0]] += 1
            continue
        # 退化正文不进零起点集（否则等于把要清掉的毛病教回去）
        codes, _ = C.degen_codes(body)
        if codes:
            rej["degenerate"] += 1
            for x in codes:
                degen_detail[x] += 1
            continue
        cands.append({
            "idx": i,
            "body": body,
            "sys": sysmsg,
            "scene": scene,
            "strict": C.strict_count(body),
            "adult_injected": adult_injected,
        })
    print("[cand] pass=%d  reject=%s" % (len(cands), dict(rej)))

    # ---- 确定性洗牌 + 去重（exact + MinHash-LSH 近重） --------------
    rnd = random.Random(C.SEED)
    rnd.shuffle(cands)

    seen_norm = set()
    kept = []
    sh_cache = {}          # kept_id -> shingle set（只对 LSH 命中项做精确 Jaccard）
    bands, rows_per = 8, 4
    buckets = [dict() for _ in range(bands)]

    def mh_sig(sh):
        arr = np.fromiter((zlib.crc32(s.encode("utf-8")) for s in sh),
                          dtype=np.uint64, count=len(sh))
        return [int(((arr * np.uint64(1000003 + k)) + np.uint64(k * 2654435761))
                    .min()) for k in range(bands * rows_per)]

    for c in cands:
        key = C.common.norm_text(c["body"])
        if key in seen_norm:
            rej["dup_exact"] += 1
            continue
        sh = C.common.shingles(c["body"], k=5)
        if not sh:
            rej["dup_exact"] += 1
            continue
        sig = mh_sig(sh)
        cand_ids = set()
        for b in range(bands):
            k = (b, tuple(sig[b * rows_per:(b + 1) * rows_per]))
            cand_ids.update(buckets[b].get(k, ()))
        dup = False
        for j in cand_ids:
            if C.common.jaccard(sh, sh_cache[j]) >= NEAR_DUP_JACCARD:
                dup = True
                break
        if dup:
            rej["dup_near"] += 1
            continue
        seen_norm.add(key)
        kid = len(kept)
        sh_cache[kid] = sh
        for b in range(bands):
            k = (b, tuple(sig[b * rows_per:(b + 1) * rows_per]))
            buckets[b].setdefault(k, []).append(kid)
        kept.append(c)
    print("[dedup] kept=%d  (dup_exact=%d dup_near=%d)"
          % (len(kept), rej["dup_exact"], rej["dup_near"]))

    # ---- 场景配额 round-robin --------------------------------------
    by_scene = OrderedDict((s, []) for s in SCENE_CAPS)
    for c in kept:
        by_scene.setdefault(c["scene"], []).append(c)

    picked = []
    scene_take = Counter()
    while len(picked) < args.target:
        progressed = False
        for s in SCENE_CAPS:
            if len(picked) >= args.target:
                break
            pool = by_scene.get(s) or []
            if scene_take[s] >= SCENE_CAPS[s] or not pool:
                continue
            picked.append(pool.pop(0))
            scene_take[s] += 1
            progressed = True
        if not progressed:
            break
    print("[pick] rows=%d  scene=%s" % (len(picked), dict(scene_take)))

    # ---- 组样本 ----------------------------------------------------
    out = []
    tmpl_cnt = Counter()
    for i, c in enumerate(picked):
        adult_note = (c["scene"] == "校园") or bool(C.common.soft_hits(c["body"]))
        head = build_head(c["scene"], adult_note)
        tpl = TEMPLATES[(i * 5 + 1) % len(TEMPLATES)]
        n = N_WORDS[(i * 7 + 3) % len(N_WORDS)]
        user = tpl.format(head=head, n=n)
        tmpl_cnt[tpl] += 1
        out.append({
            "messages": [
                {"role": "system", "content": c["sys"]},
                {"role": "user", "content": user},
                {"role": "assistant", "content": c["body"]},
            ]
        })

    # ---- 统计 ------------------------------------------------------
    bodies = [o["messages"][2]["content"] for o in out]
    stricts = [C.strict_count(b) for b in bodies]
    lens = [len(b) for b in bodies]
    stats = {
        "generated_at": "2026-11-21",
        "seed": C.SEED,
        "params": {
            "min_strict": MIN_STRICT, "body_len": BODY_LEN,
            "near_dup_jaccard": NEAR_DUP_JACCARD, "target": args.target,
            "scene_caps": dict(SCENE_CAPS),
        },
        "input": {"rows": len(rows), "permit": len(permit)},
        "reject": dict(rej),
        "reject_degenerate_detail": dict(degen_detail),
        "rows": len(out),
        "unique_assistant": len(set(bodies)),
        "unique_assistant_norm": len({C.common.norm_text(b) for b in bodies}),
        "strict": {
            "mean": C.fmt(sum(stricts) / len(stricts)) if stricts else 0,
            "min": min(stricts) if stricts else 0,
            "max": max(stricts) if stricts else 0,
            "ge5_ratio": C.fmt(sum(1 for x in stricts if x >= 5) / len(stricts)) if stricts else 0,
            "ge8_ratio": C.fmt(sum(1 for x in stricts if x >= 8) / len(stricts)) if stricts else 0,
        },
        "len": {
            "mean": int(sum(lens) / len(lens)) if lens else 0,
            "min": min(lens) if lens else 0,
            "max": max(lens) if lens else 0,
        },
        "scene": dict(Counter(c["scene"] for c in picked)),
        "adult_decl_injected": sum(1 for c in picked if c.get("adult_injected")),
        "user_template": {"t%d" % i: v for i, (t, v) in enumerate(
            sorted(tmpl_cnt.items(), key=lambda kv: -kv[1]))},
        "system_verbatim": all(o["messages"][0]["content"] == C.SYS_PERMIT for o in out),
        "degenerate_hits": sum(1 for b in bodies if C.degen_codes(b)[0]),
    }

    dst = os.path.join(C.OUT_DIR, "nsfw-zeroshot.jsonl")
    if not args.dry_run:
        C.write_jsonl(dst, out)
        C.write_json(os.path.join(C.WORK, "zeroshot-stats.json"), stats)
        print("[out] %s" % dst)
    print("[stats] rows=%d unique=%d strict_mean=%s ge5=%s scene=%s"
          % (stats["rows"], stats["unique_assistant"], stats["strict"]["mean"],
             stats["strict"]["ge5_ratio"], stats["scene"]))


if __name__ == "__main__":
    main()
