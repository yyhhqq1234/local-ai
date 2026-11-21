# -*- coding: utf-8 -*-
"""01 输入体检：分支分布、各门命中规模、重复率粗测。只读。"""
import collections
import json
import os

from common import (
    IN_V5, IN_POS, IN_NEG, IN_DSH, WORK, branch_of, msg_pair, all_text,
    minor_hit, soft_hits, has_adult_decl, refusal_hit, template_hit,
    has_dialogue, has_action, read_jsonl, norm_text, jaccard, shingles,
)


def profile(path, label):
    rows = read_jsonl(path)
    br = collections.Counter()
    gates = collections.Counter()
    soft_detail = collections.Counter()
    minor_examples = []
    alen = []
    user_seen = collections.Counter()
    for r in rows:
        b = branch_of(r["messages"])
        br[b] += 1
        u, a = msg_pair(r)
        t = all_text(r)
        hit, reason = minor_hit(t)
        if hit:
            gates["minor_hard"] += 1
            if len(minor_examples) < 8:
                minor_examples.append(reason)
        sw = soft_hits(t)
        if sw:
            soft_detail.update(sw)
            if not has_adult_decl(t):
                gates["soft_no_adult_decl"] += 1
            else:
                gates["soft_with_adult_decl"] += 1
        if refusal_hit(a):
            gates["refusal"] += 1
        if template_hit(a):
            gates["template"] += 1
        if len(a) < 200 and not has_dialogue(a):
            gates["short_nodialog"] += 1
        if not has_dialogue(a) and not has_action(a):
            gates["outline_like"] += 1
        alen.append(len(a))
        user_seen[norm_text(u)] += 1
    alen.sort()
    exact_dup = sum(v - 1 for v in user_seen.values() if v > 1)
    print(f"\n=== {label} n={len(rows)} ===")
    print("branch:", dict(br))
    print("gates:", dict(gates))
    print("soft detail:", dict(soft_detail))
    print("minor reasons sample:", minor_examples)
    print(f"alen p50={alen[len(alen)//2]} p95={alen[int(len(alen)*0.95)]} min={alen[0]} max={alen[-1]}")
    print(f"user-only exact dup rows={exact_dup} unique={len(user_seen)}")
    return {"n": len(rows), "branch": dict(br), "gates": dict(gates)}


if __name__ == "__main__":
    os.makedirs(WORK, exist_ok=True)
    res = {}
    for path, label in ((IN_V5, "v5"), (IN_POS, "gate-pos"), (IN_NEG, "gate-neg"), (IN_DSH, "dsh")):
        res[label] = profile(path, label)
    with open(os.path.join(WORK, "00-profile.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nwrote 00-profile.json")
