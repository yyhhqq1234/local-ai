# -*- coding: utf-8 -*-
"""02 NSFW 门控集清洗。

输入（只读）：train-2b-gated-v5.jsonl（主力）+ gate-pos/gate-neg（补充）
输出：data/nsfw-gated/cleaned/nsfw-clean.jsonl
      data/nsfw-gated/cleaned/nsfw-clean-paired.jsonl（同 user 两分支都在的完整对）
      data/nsfw-gated/cleaned/nsfw-lowquality.jsonl（low_quality 分区，不混入主集）
      _work/clean/nsfw/drops-nsfw.jsonl · nsfw-run.json

门序（单次归因，先命中先记账）：
  1 hard_minor   → 删（未成年硬闸；萝莉需+年龄/学段线索）
  2 soft_minor   → 无成年声明则删
  3 refusal      → 仅许可分支删（常规分支保留）
  4 template     → 许可/常规分支都删（策略见 report）
  5 leak(eval)   → 删（user 前 200 字命中 eval）
  6 short_nodialog(<200字且无对白) → 仅许可分支删
  7 exact dedup  → 同分支 (user,assistant) 归一后重复，保留首条
  8 near dedup   → 同分支内 assistant 5-gram Jaccard ≥0.9 删
  9 low_quality  → 不打删，另落分区
"""
import collections
import hashlib
import json
import os

import numpy as np

from common import (
    IN_V5, IN_POS, IN_NEG, OUT_DIR, WORK,
    branch_of, msg_pair, all_text, minor_eval, soft_hits, has_adult_decl,
    refusal_hit, template_hit, template_rewrite, has_dialogue, has_action, norm_text,
    load_eval_users, load_lexicon_terms, read_jsonl, write_jsonl, jaccard,
    shingle_hashes,
)

SYS_PERMIT = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
SYS_REGULAR = "模式：常规（未授权成人向内容）。不含露骨性描写。"


class MH:
    """MinHash + banded LSH（32 perm / 8 band x 4 row），numpy 实现。"""

    def __init__(self, num_perm=32, bands=8):
        self.num_perm = num_perm
        self.rows = num_perm // bands
        self.bands = bands
        rng = np.random.default_rng(20261121)
        self.seeds = rng.integers(1, 2 ** 62, size=num_perm, dtype=np.int64).astype(np.uint64)
        self.buckets = [dict() for _ in range(bands)]

    def sig(self, h):
        if h.size == 0:
            return None
        return (h[:, None] ^ self.seeds[None, :]).min(axis=0)

    def query(self, sig):
        out = []
        for b in range(self.bands):
            key = tuple(int(x) for x in sig[b * self.rows:(b + 1) * self.rows])
            if key in self.buckets[b]:
                out.extend(self.buckets[b][key])
        return out

    def add(self, i, sig):
        for b in range(self.bands):
            key = tuple(int(x) for x in sig[b * self.rows:(b + 1) * self.rows])
            self.buckets[b].setdefault(key, []).append(i)


def normalize_messages(messages, br):
    """保证每条都带该分支的规范 system 行（旧版很多行没有 system）。"""
    has_sys = any(m.get("role") == "system" for m in messages)
    if has_sys:
        return messages
    sysmsg = SYS_PERMIT if br == "permit" else SYS_REGULAR
    return [{"role": "system", "content": sysmsg}] + list(messages)


def main():
    v5 = read_jsonl(IN_V5)
    pos = read_jsonl(IN_POS)
    neg = read_jsonl(IN_NEG)

    eval_keys, eval_n = load_eval_users()
    lex_terms = load_lexicon_terms()
    print(f"[in] v5={len(v5)} pos={len(pos)} neg={len(neg)} eval_users={eval_n} lex_terms={len(lex_terms)}")

    def fp(row):
        u, a = msg_pair(row)
        return (branch_of(row), norm_text(u), norm_text(a))

    cand = list(v5)
    seen = {fp(r) for r in v5}
    added = 0
    for r in pos + neg:
        k = fp(r)
        if k in seen:
            continue
        seen.add(k)
        cand.append(r)
        added += 1
    print(f"[merge] 旧版补充 {added} 条（去重后候选 {len(cand)}）")

    stats = {
        "input": {"v5": len(v5), "gate_pos": len(pos), "gate_neg": len(neg),
                  "eval_user_keys": eval_n, "supplement_added": added,
                  "candidates": len(cand)},
        "drops": collections.Counter(),
        "drop_by_branch": collections.Counter(),
        "minor_reason": collections.Counter(),
        "soft_word": collections.Counter(),
        "refusal_reason": collections.Counter(),
        "template_reason": collections.Counter(),
        "template_rewrite_reason": collections.Counter(),
        "template_rewritten": 0,
    }
    drops, kept, lowq = [], [], []
    loli = {"present_total": 0, "old_would_drop": 0, "gated_metrics": 0,
            "dropped_other_gate": 0, "dropped_dedup": 0, "restored": 0}

    for idx, row in enumerate(cand):
        u, a = msg_pair(row)
        t = all_text(row)
        br = branch_of(row)
        reason = None

        me = minor_eval(t)
        if me["loli_present"]:
            loli["present_total"] += 1      # 旧口径：含"萝莉"即删
        if me["loli_only"]:
            loli["old_would_drop"] += 1     # 旧口径下仅凭萝莉就判死
        if me["hit"]:
            reason = "hard_minor"
            stats["minor_reason"][me["reason"]] += 1
            if me["loli_gated"]:
                loli["gated_metrics"] += 1
        elif soft_hits(t) and not has_adult_decl(t):
            reason = "soft_minor"
            stats["soft_word"].update(soft_hits(t))
        elif br == "permit" and refusal_hit(a):
            reason = "refusal"
            stats["refusal_reason"].update(refusal_hit(a))
        elif template_hit(a):
            if br == "permit":
                reason = "template"
                stats["template_reason"].update(template_hit(a))
            else:
                # 常规分支：改写而非整条删（保留正文信息）
                rw = template_rewrite(a)
                if template_hit(rw) or len(rw) < 120:
                    reason = "template"
                    stats["template_reason"].update(template_hit(a))
                else:
                    stats["template_rewritten"] += 1
                    stats["template_rewrite_reason"].update(template_hit(a))
                    a = rw
        elif norm_text(u[:200]) in eval_keys:
            reason = "leak_eval"
        elif br == "permit" and len(a) < 200 and not has_dialogue(a):
            reason = "short_nodialog"

        if reason:
            stats["drops"][reason] += 1
            stats["drop_by_branch"][(reason, br)] += 1
            if me["loli_present"] and reason != "hard_minor":
                loli["dropped_other_gate"] += 1
            drops.append({"i": idx, "branch": br, "reason": reason,
                          "why": me["reason"] if reason == "hard_minor" else "",
                          "user_sha1": hashlib.sha1(norm_text(u).encode()).hexdigest()[:16],
                          "user_len": len(u)})
            continue

        msgs = normalize_messages(row["messages"], br)
        if a != (row["messages"][-1].get("content") or ""):
            msgs = list(msgs)
            for mi in range(len(msgs) - 1, -1, -1):
                if msgs[mi].get("role") == "assistant":
                    msgs[mi] = {"role": "assistant", "content": a}
                    break
        kept.append({"messages": msgs, "_br": br, "_u": u, "_a": a,
                     "_loli": me["loli_only"]})

    print(f"[gate] 过门 {len(kept)}，删 {len(drops)} {dict(stats['drops'])}")

    # ---------------- 精确去重（分支内）
    exact, stage2, dup_exact = set(), [], 0
    for rec in kept:
        key = (rec["_br"], norm_text(rec["_u"]), norm_text(rec["_a"]))
        if key in exact:
            dup_exact += 1
            stats["drop_by_branch"][("dup_exact", rec["_br"])] += 1
            if rec["_loli"]:
                loli["dropped_dedup"] += 1
            drops.append({"i": -1, "branch": rec["_br"], "reason": "dup_exact",
                          "user_sha1": hashlib.sha1(norm_text(rec["_u"]).encode()).hexdigest()[:16]})
            continue
        exact.add(key)
        stage2.append(rec)
    stats["drops"]["dup_exact"] = dup_exact
    print(f"[dedup] 精确重复 {dup_exact} → {len(stage2)}")

    # ---------------- 近似去重（分支内，assistant 5-gram ≥0.9）
    mh = MH()
    reps, kept_near, dup_near = [], [], 0
    for rec in stage2:
        h = shingle_hashes(rec["_a"])
        sig = mh.sig(h)
        cands = mh.query(sig) if sig is not None else []
        set_a, is_dup = None, False
        for ci in cands:
            br_rep, rep_set = reps[ci]
            if br_rep != rec["_br"]:
                continue
            if set_a is None:
                set_a = {int(x) for x in h}
            if jaccard(set_a, rep_set) >= 0.9:
                is_dup = True
                break
        if is_dup:
            dup_near += 1
            stats["drop_by_branch"][("dup_near", rec["_br"])] += 1
            if rec["_loli"]:
                loli["dropped_dedup"] += 1
            drops.append({"i": -1, "branch": rec["_br"], "reason": "dup_near",
                          "user_sha1": hashlib.sha1(norm_text(rec["_u"]).encode()).hexdigest()[:16]})
            continue
        mh.add(len(reps), sig)
        reps.append((rec["_br"], {int(x) for x in h}))
        kept_near.append(rec)
    stats["drops"]["dup_near"] = dup_near
    print(f"[dedup] 近似重复 {dup_near} → {len(kept_near)}")

    # ---------------- 结果组装 / 低质分区
    def is_explicit(text):
        return len({w for w in lex_terms if w in text}) >= 2

    final, final_br, lowq = [], [], []
    for rec in kept_near:
        out = {"messages": rec["messages"]}
        if not has_dialogue(rec["_a"]) and not has_action(rec["_a"]):
            lowq.append({**out, "meta": {"low_quality": True,
                                         "reason": "outline_no_dialogue_no_action"}})
            continue
        final.append(out)
        final_br.append(rec["_br"])

    stats["drops"]["low_quality_moved"] = len(lowq)
    stats["final"] = len(final)
    loli["restored"] = loli["old_would_drop"] - loli["dropped_dedup"]

    # ---------------- 成对视图 / 统计
    pair_map = collections.defaultdict(dict)
    for r, br in zip(final, final_br):
        pair_map[norm_text(msg_pair(r)[0])][br] = r
    paired_rows = []
    for uq, d in pair_map.items():
        if len(d) == 2:
            paired_rows.extend([d["permit"], d["regular"]])
    paired_users = len(paired_rows) // 2

    br_final = collections.Counter(final_br)
    alen = sorted(len(r["messages"][-1]["content"]) for r in final)
    ulen = sorted(len(msg_pair(r)[0]) for r in final)
    explicit = sum(1 for r in final if is_explicit(r["messages"][-1]["content"]))

    def pct(n, d):
        return round(100.0 * n / d, 2) if d else 0.0

    def q(arr, p):
        return arr[min(len(arr) - 1, int(len(arr) * p))] if arr else 0

    stats.update({
        "final_branch": dict(br_final),
        "explicit_count": explicit,
        "explicit_ratio_pct": pct(explicit, len(final)),
        "assistant_len": {"p50": q(alen, 0.5), "p95": q(alen, 0.95),
                          "min": alen[0] if alen else 0, "max": alen[-1] if alen else 0},
        "user_len": {"p50": q(ulen, 0.5), "p95": q(ulen, 0.95)},
        "paired_users": paired_users,
        "paired_rows": len(paired_rows),
        "loli_correction": loli,
    })
    stats["drops"] = dict(stats["drops"])
    stats["drop_by_branch"] = {f"{k[0]}|{k[1]}": v for k, v in stats["drop_by_branch"].items()}
    for k in ("minor_reason", "soft_word", "refusal_reason", "template_reason",
              "template_rewrite_reason"):
        stats[k] = dict(stats[k].most_common())

    os.makedirs(OUT_DIR, exist_ok=True)
    write_jsonl(os.path.join(OUT_DIR, "nsfw-clean.jsonl"), final)
    write_jsonl(os.path.join(OUT_DIR, "nsfw-clean-paired.jsonl"), paired_rows)
    write_jsonl(os.path.join(OUT_DIR, "nsfw-lowquality.jsonl"), lowq)
    write_jsonl(os.path.join(WORK, "drops-nsfw.jsonl"), drops)
    with open(os.path.join(WORK, "nsfw-run.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    keys = ("input", "drops", "final", "final_branch", "explicit_ratio_pct",
            "assistant_len", "paired_users", "paired_rows", "loli_correction")
    print("\n=== 结果 ===")
    print(json.dumps({k: stats[k] for k in keys}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
