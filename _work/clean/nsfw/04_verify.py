# -*- coding: utf-8 -*-
"""04 复核：对 cleaned 产物重新跑一遍全部门，任何残留违例都必须为 0。"""
import collections
import json
import os
import re

import numpy as np

from common import (
    OUT_DIR, WORK, branch_of, msg_pair, all_text, minor_eval, soft_hits,
    has_adult_decl, refusal_hit, template_hit, has_dialogue, norm_text,
    load_eval_users, read_jsonl, jaccard, shingle_hashes,
)
import importlib.util

spec = importlib.util.spec_from_file_location("dsh", os.path.join(WORK, "03_clean_dsh.py"))
dsh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dsh)


def lsh_dup_pairs(rows, threshold=0.9, k=5):
    """复核用：暴力 LSH（32 perm）找同分支 near-dup 对，返回 (对数, 最大 jaccard)。"""
    from importlib import import_module
    m2 = import_module("02_clean_nsfw".replace("02", "run_03")) if False else None
    # 复用 02 的 MH 会重名冲突，这里直接内置
    num_perm, bands = 32, 8
    rows_ = num_perm // bands
    rng = np.random.default_rng(20261121)
    seeds = rng.integers(1, 2 ** 62, size=num_perm, dtype=np.int64).astype(np.uint64)
    buckets = [dict() for _ in range(bands)]
    maxj = 0.0
    pairs = 0
    reps = []
    for r in rows:
        br = branch_of(r)
        h = shingle_hashes(r["messages"][-1]["content"], k)
        if h.size == 0:
            continue
        sig = (h[:, None] ^ seeds[None, :]).min(axis=0)
        cand = set()
        for b in range(bands):
            key = tuple(int(x) for x in sig[b * rows_:(b + 1) * rows_])
            cand.update(buckets[b].get(key, []))
        s = {int(x) for x in h}
        for ci in cand:
            if reps[ci][0] != br:
                continue
            j = jaccard(s, reps[ci][1])
            if j >= threshold:
                pairs += 1
                maxj = max(maxj, j)
        for b in range(bands):
            key = tuple(int(x) for x in sig[b * rows_:(b + 1) * rows_])
            buckets[b].setdefault(key, []).append(len(reps))
        reps.append((br, s))
    return pairs, round(maxj, 4)


def verify_nsfw():
    path = os.path.join(OUT_DIR, "nsfw-clean.jsonl")
    rows = read_jsonl(path)
    eval_keys, _ = load_eval_users()
    v = collections.Counter()
    no_sys = 0
    for r in rows:
        u, a = msg_pair(r)
        t = all_text(r)
        br = branch_of(r)
        if not any(m.get("role") == "system" for m in r["messages"]):
            no_sys += 1
        me = minor_eval(t)
        if me["hit"]:
            v["minor"] += 1
            v[f"minor:{me['reason']}"] += 1
        if soft_hits(t) and not has_adult_decl(t):
            v["soft"] += 1
        if br == "permit" and refusal_hit(a):
            v["refusal_permit"] += 1
        if template_hit(a):
            v["template"] += 1
        if norm_text(u[:200]) in eval_keys:
            v["leak"] += 1
        if br == "permit" and len(a) < 200 and not has_dialogue(a):
            v["short_nodialog_permit"] += 1
    pairs, maxj = lsh_dup_pairs(rows, 0.9)
    v["near_dup_pairs>=0.9"] = pairs
    v["near_dup_max_jaccard"] = maxj
    v["no_system"] = no_sys
    v["rows"] = len(rows)
    return dict(v)


def verify_dsh():
    path = os.path.join(OUT_DIR, "dsh-clean.jsonl")
    rows = read_jsonl(path)
    manifest = dsh.load_manifest()
    v = collections.Counter()
    seen = set()
    for r in rows:
        a = r["messages"][-1]["content"]
        u = r["messages"][1]["content"]
        for k, rx in dsh.VIOL_PATTERNS.items():
            if rx.search(a):
                v["viol_" + k] += 1
        for m in dsh.TOOL_CALL_RE.finditer(a):
            try:
                obj = json.loads(m.group(1))
            except Exception:
                v["toolcall_unparsable"] += 1
                continue
            ok, probs = dsh.validate_call(obj, manifest)
            v["toolcall_ok" if ok else "toolcall_bad"] += 1
            for p in probs:
                v["prob:" + p.split(":")[0]] += 1
        key = (norm_text(u), norm_text(a))
        if key in seen:
            v["exact_dup"] += 1
        seen.add(key)
    v["rows"] = len(rows)
    return dict(v)


if __name__ == "__main__":
    res = {"nsfw": verify_nsfw(), "dsh": verify_dsh()}
    with open(os.path.join(WORK, "verify.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))

    bad = []
    ns = res["nsfw"]
    for k in ("minor", "soft", "refusal_permit", "template", "leak",
              "short_nodialog_permit", "no_system"):
        if ns.get(k, 0):
            bad.append(f"nsfw:{k}={ns[k]}")
    if ns.get("near_dup_pairs>=0.9", 0):
        bad.append(f"nsfw:near_dup_pairs={ns['near_dup_pairs>=0.9']}")
    ds = res["dsh"]
    for k, val in ds.items():
        if k.startswith(("viol_", "toolcall_bad", "prob:", "toolcall_unparsable", "exact_dup")) and val:
            bad.append(f"dsh:{k}={val}")
    print("\nVERDICT:", "PASS" if not bad else "FAIL " + "; ".join(bad))
