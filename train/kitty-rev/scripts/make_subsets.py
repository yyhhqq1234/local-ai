#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_subsets.py -- split data/large-mix/train.jsonl into category subsets with
a mandatory held-out validation split.

Why a val split is not optional
    359 samples at ga=8 is ~45 micro-batches per epoch, so 120 steps is 3.4
    epochs: overfitting is guaranteed, not likely.  Without val loss you cannot
    tell "learned the reverse-engineering knowledge" from "memorised these 359
    rows", and the whole targeted-training idea becomes unfalsifiable.

Dedup is by CONTENT HASH, not by source line number
    The same conversation appears in several categories (large-mix was built by
    merging harvests), so a row-level split leaks eval rows into train.  Every
    row is hashed over its normalised `messages` list; a hash already seen is
    dropped by default (--keep-dup to override).

Outputs (under --out-dir)
    re-subset.jsonl            all rows of the group, original order
    re-subset.train.jsonl      the train part
    re-subset.val.jsonl        the 20% held-out part
    ... same for route / discipline
    subsets_manifest.json      counts, sha256, dedup stats, seed

Usage
    python make_subsets.py --data data/large-mix/train.jsonl --out-dir data/subsets
    python make_subsets.py ... --dry-run            # report only, write nothing
    python make_subsets.py ... --val-ratio 0.15 --seed 7
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time

GROUPS = {
    "re": ["kb-re", "action-reverse"],
    "route": ["tool-route"],
    "discipline": ["real-discipline"],
    # generic replay set: mixed in at 逆向:通用 = 4:1 so 359 reverse rows cannot
    # drag the last 16 layers off-distribution (catastrophic forgetting)
    "gen": ["reasoning"],
    # ["*"] = 用 SELECTORS[forge] 的行级判据切，不按 cat（见 SELECTORS 注释）
    "forge": ["*"],
    # comply = 配合意愿四类（data/intent2，各 100）。按 cat 显式列举而不是前缀匹配：
    # cat 名是稳定契约，前缀匹配会在将来新增 comply-e 时静默并进来（宁可报 0 也不要默默变大）。
    # 注意 EXCLUDE_FORGE 不含 comply —— comply 行没有 meta.forge，不会被剔除。
    "comply": ["comply-a", "comply-b", "comply-c", "comply-d"],
}
# a group may cap how many rows it keeps (gen is a sample, not a whole category)
CAPS = {"gen": 100}
# Groups selected by a row PREDICATE instead of cat membership.
#   forge = data/forge 产出的高密度逆向样本（meta.forge 存在即入选）。
#   WHY not by cat: op-syntax（473 条）/ real-trajectory 两个 cat 里混着大量旧的
#   模板式低密度行，按 cat 整体并入会把 4 倍密度的 forge 样本稀释掉。逆向权重靠
#   训练侧分层采样（forge:4 / re:2 / rest:1）来拿，不靠在切分侧混池。
SELECTORS = {
    "forge": lambda r: bool((r.get("meta") or {}).get("forge")),
}
# gen must be disjoint from the targeted groups -- asserted, not just reported
DISJOINT = {"gen": ["re", "route", "discipline"]}
# forge 是独立池：目标组若重复收 forge 行，`forge:4,re-train:2` 里那部分实际权重
# 会变成 6 而非 4，配比表失去可解释性（lead 裁决 A）。
EXCLUDE_FORGE = {"re", "route", "discipline"}
# reference counts on 2026-10-21; a mismatch is reported, not fatal
EXPECT = {
    "re": {"kb-re": 194, "action-reverse": 165, "total": 359},
    "route": {"tool-route": 292, "total": 292},
    "discipline": {"real-discipline": 383, "total": 383},
    "gen": {"reasoning": 100, "total": 100},
    # forge 目标 480（四类各 120）；实得少于目标时只报警不失败
    "forge": {"total": 480},
    # comply 目标 400（四类各 100）；本轮不参与训练，下轮启用
    "comply": {"total": 400},
}


def content_hash(row):
    """Stable hash of the conversation itself -- ignores timestamps, ids, meta."""
    msgs = row.get("messages") or []
    norm = [{"role": m.get("role", ""), "content": (m.get("content") or "").strip()}
            for m in msgs]
    blob = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def file_sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16], os.path.getsize(path)


# --------------------------------------------------------------------------- #
# refusal scan (§16)
#   The model is abliterated: its refusal behaviour was surgically removed.  Any
#   replay data whose assistant turns carry the official Qwen alignment voice
#   ("as an AI I cannot...") trains that refusal straight back in, cancelling the
#   abliteration.  Scan every subset before it can be used for training.
# --------------------------------------------------------------------------- #
REFUSAL_PATTERNS = [
    r"(抱歉|对不起|很遗憾)[，,].{0,12}(不能|无法|不便|不可以)",
    r"(作为|身为)(一个)?\s*(AI|人工智能|语言模型)",
    # English must require a REFUSAL ACTION next to the modal.  A bare
    # "I can't / I cannot" is ordinary chain-of-thought ("I can't just make x76
    # huge", "I cannot call any of the provided functions") -- matching it
    # produced 7/7 false positives on the first run.
    r"I (?:can't|cannot|am unable to|must decline)\s+(?:help|assist|provide|comply|support|do that|answer that|fulfill|engage|share)",
    r"I (?:can't|cannot)\s+(?:help|assist)\s+with\s+(?:that|this|such|these|requests?)",
    r"(违反|违背).{0,8}(政策|准则|规定|法律)",
    r"(不提供|不予).{0,6}(帮助|协助|支持).{0,6}(此类|这类|该)",
    r"(建议|请)(咨询|联系).{0,10}(专业人士|律师|相关部门)",
]
REFUSAL_BLOCK_RATE = 0.02     # >2% hits -> the subset may not be used for training


def scan_refusals(rows, patterns=None):
    """-> {content_hash: {pattern, match, cat, src, snippet}} for every refusing row."""
    patterns = patterns or REFUSAL_PATTERNS
    hits = {}
    for r in rows:
        m0 = r.get("meta") or {}
        # §17 intent data is DELIBERATELY non-refusing; filtering it would delete
        # exactly the behaviour we are trying to install.
        if m0.get("intent"):
            continue
        # forge rows are high-density reverse samples selected by a row-level
        # SELECTOR; they are meant to teach "answer directly", so a lexical
        # refusal hit here would be a false positive on the teaching material.
        if m0.get("forge"):
            continue
        txt = " ".join((m.get("content") or "") for m in (r.get("messages") or [])
                       if m.get("role") == "assistant")
        if not txt:
            continue
        for i, pat in enumerate(patterns):
            m = re.search(pat, txt, re.I)
            if m:
                hits[r["_hash"]] = {
                    "pattern": i, "match": m.group(0)[:80],
                    "cat": (r.get("meta") or {}).get("cat"),
                    "src": r.get("_src_line"),
                    "snippet": txt[max(0, m.start() - 60):m.start() + 120],
                }
                break
    return hits


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description="category subsets with mandatory val split")
    ap.add_argument("--data", default="data/large-mix/train.jsonl")
    ap.add_argument("--out-dir", default="data/subsets")
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--groups", default="",
                    help='覆盖分组，形如 "re=kb-re+action-reverse;route=tool-route"')
    ap.add_argument("--keep-dup", action="store_true", help="保留跨类别重复内容（默认去重）")
    ap.add_argument("--min-val", type=int, default=8, help="验证集最少条数（不足则从 train 挪）")
    ap.add_argument("--filter-refusal", action=argparse.BooleanOptionalAction, default=True,
                    help="剔除 assistant 段含拒答话术的行（默认开；--no-filter-refusal 只扫描不剔除）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    groups = dict(GROUPS)
    if a.groups:
        groups = {}
        for part in a.groups.split(";"):
            if "=" not in part:
                continue
            name, cats = part.split("=", 1)
            groups[name.strip()] = [c.strip() for c in cats.split("+") if c.strip()]

    rows = []
    with open(a.data, encoding="utf-8") as f:
        for ln, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception as e:
                print(f"[warn] line {ln} 解析失败: {e}")
                continue
            r["_src_line"] = ln
            r["_hash"] = content_hash(r)
            rows.append(r)
    print(f"[read] {len(rows)} 行  {a.data}")

    # content-level dedup (first occurrence wins, source order preserved)
    seen, uniq, dup = set(), [], 0
    for r in rows:
        if r["_hash"] in seen and not a.keep_dup:
            dup += 1
            continue
        seen.add(r["_hash"])
        uniq.append(r)
    print(f"[dedup] 唯一 {len(uniq)} 行，丢弃重复 {dup} 行（按 messages 内容哈希）")

    by_cat = {}
    for r in uniq:
        c = (r.get("meta") or {}).get("cat", "?")
        by_cat.setdefault(c, []).append(r)
    print(f"[cats] {len(by_cat)} 类: " +
          ", ".join(f"{k}={len(v)}" for k, v in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))))

    # ---- refusal scan (§16) -------------------------------------------------
    refusal_hits = scan_refusals(uniq)
    ref_by_cat = {}
    for _h, d in refusal_hits.items():
        ref_by_cat.setdefault(d["cat"], []).append(d)
    print(f"[refusal] 扫描 {len(uniq)} 行 → 命中 {len(refusal_hits)} 行 "
          f"({len(refusal_hits) / max(1, len(uniq)) * 100:.2f}%)"
          f"{'  → 已剔除' if a.filter_refusal else '  → 只报告未剔除'}")
    for c, ds in sorted(ref_by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"[refusal]   {c:22s} hits={len(ds)}")

    rng = random.Random(a.seed)
    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": os.path.abspath(a.data),
        "source_sha16": file_sha16(a.data)[0] if os.path.exists(a.data) else None,
        "seed": a.seed, "val_ratio": a.val_ratio, "keep_dup": a.keep_dup,
        "dedup": {"source_rows": len(rows), "unique": len(uniq), "dropped": dup},
        "groups": {},
    }
    os.makedirs(a.out_dir, exist_ok=True)

    ok = True
    used = set()          # hashes already claimed by earlier groups
    group_hashes = {}     # gname -> set(hash), for the no-overlap assertion
    for gname, cats in groups.items():
        pool = []
        cat_counts = {}
        removed_disjoint = 0
        removed_forge = 0
        raw_n = raw_ref = 0
        sel = SELECTORS.get(gname)
        if cats == ["*"] and sel is None:
            print(f"[{gname}][FATAL] 组 {gname} 声明为 ['*'] 但 SELECTORS 里没有对应判据")
            ok = False
            continue
        if cats == ["*"]:
            # 行级判据分组：cat 列表由命中行反推，pool 只收命中行
            buckets = {}
            for r in uniq:
                if sel(r):
                    buckets.setdefault((r.get("meta") or {}).get("cat", "?"), []).append(r)
            cats = sorted(buckets)
        else:
            buckets = {c: list(by_cat.get(c, [])) for c in cats}
        for c in cats:
            lst = buckets[c]
            if gname in DISJOINT:
                before = len(lst)
                lst = [r for r in lst if r["_hash"] not in used]
                removed_disjoint += before - len(lst)
            # 裁决 A：目标组剔除 forge 行，保证 `forge:4,re-train:2` 的权重语义干净
            if gname in EXCLUDE_FORGE:
                before = len(lst)
                lst = [r for r in lst
                       if not (r.get("meta") or {}).get("forge")]
                removed_forge += before - len(lst)
            raw_n += len(lst)
            raw_ref += sum(1 for r in lst if r["_hash"] in refusal_hits)
            if a.filter_refusal:
                lst = [r for r in lst if r["_hash"] not in refusal_hits]
            rng.shuffle(lst)
            cat_counts[c] = len(lst)
            pool.extend(lst)
        if not pool:
            print(f"[{gname}][warn] 0 条（类别 {cats} 不存在或已被不相交规则清空）")
            continue
        cap = CAPS.get(gname, 0)
        if cap and len(pool) > cap:
            rng.shuffle(pool)
            pool = pool[:cap]
            cat_counts = {c: sum(1 for r in pool
                                 if ((r.get("meta") or {}).get("cat") == c)) for c in cats}
        # stratified split over the (possibly capped) pool, which is already shuffled
        train, val = [], []
        for c in cats:
            lst = [r for r in pool if ((r.get("meta") or {}).get("cat") == c)]
            n_val = max(1, int(round(len(lst) * a.val_ratio))) if lst else 0
            val.extend(lst[:n_val])
            train.extend(lst[n_val:])
        # guard: a tiny group could starve the val split
        if len(val) < a.min_val and len(train) > (a.min_val - len(val)):
            need = a.min_val - len(val)
            rng.shuffle(train)
            val.extend(train[:need])
            train = train[need:]
        # leak check: content hashes must be disjoint
        leak = {r["_hash"] for r in train} & {r["_hash"] for r in val}
        if leak:
            ok = False
            print(f"[{gname}][FATAL] 训练/验证内容泄漏 {len(leak)} 条")
        # cross-group disjoint assertion (gen must not reuse targeted rows)
        cross = set()
        if gname in DISJOINT:
            cross = {r["_hash"] for r in pool} & used
            if cross:
                ok = False
                print(f"[{gname}][FATAL] 与 {DISJOINT[gname]} 内容重叠 {len(cross)} 条")
            else:
                print(f"[{gname}] 不相交断言通过（对 {DISJOINT[gname]}，剔除 {removed_disjoint} 条）")
        used |= {r["_hash"] for r in pool}
        exp = EXPECT.get(gname, {}).get("total")
        flag = ""
        if exp and abs(len(pool) - exp) > 0:
            flag = f"  ⚠ 期望 {exp}，实得 {len(pool)}（数据可能已更新）"

        files = {}
        if not a.dry_run:
            for tag, subset in (("all", pool), ("train", train), ("val", val)):
                path = os.path.join(a.out_dir, f"{gname}-subset{'' if tag == 'all' else '.' + tag}.jsonl")
                write_jsonl(path, subset)
                files[tag] = {"file": os.path.basename(path), "rows": len(subset)}
                h, sz = file_sha16(path)
                files[tag].update({"sha256_16": h, "bytes": sz})

        group_hashes[gname] = {r["_hash"] for r in pool}
        manifest["groups"][gname] = {
            "cats": cat_counts, "total": len(pool),
            "excluded_forge": removed_forge,
            "train": len(train), "val": len(val),
            "val_ratio_actual": round(len(val) / max(1, len(pool)), 4),
            "cap": CAPS.get(gname, 0),
            "disjoint": {"against": DISJOINT.get(gname, []),
                         "removed": removed_disjoint,
                         "overlap_after": len(cross),
                         "ok": (len(cross) == 0)},
            "refusal": {"raw": raw_n, "hits": raw_ref,
                        "rate": round(raw_ref / max(1, raw_n), 4),
                        "filtered": bool(a.filter_refusal),
                        "verdict": ("blocked"
                                    if raw_ref / max(1, raw_n) > REFUSAL_BLOCK_RATE
                                    else "ok")},
            "files": files,
        }
        print(f"[{gname}] total={len(pool)} train={len(train)} val={len(val)} "
              f"cats={cat_counts}{flag}"
              + ("" if a.dry_run else
                 f"  sha16 train={files['train']['sha256_16']} val={files['val']['sha256_16']}"))

    # cross-group overlap (informational: re/route/discipline should be disjoint)
    gh = {g: {r["_hash"] for c in cats for r in by_cat.get(c, [])} for g, cats in groups.items()}
    names = list(gh)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ov = len(gh[names[i]] & gh[names[j]])
            if ov:
                print(f"[overlap] {names[i]} ∩ {names[j]} = {ov} 条（同内容跨组，训练时可能重复计权）")

    # ---- 覆盖断言：各组互不重叠，且 并集 + 未分组 == 输入行数 ----------
    # (placed BEFORE the dry-run return so --dry-run validates the identity too)
    seen, overlaps = set(), []
    for g, hs in group_hashes.items():
        ov = seen & hs
        if ov:
            overlaps.append({"group": g, "overlap": len(ov),
                             "with": sorted(x for x in group_hashes
                                            if group_hashes[x] & ov and x != g)})
        seen |= hs
    unassigned = len(uniq) - len(seen)
    n_rows = len(uniq)
    sum_groups = sum(len(h) for h in group_hashes.values())
    if overlaps:
        ok = False
        print(f"[assert][FATAL] 组间重叠: {overlaps}")
    if sum_groups + unassigned != n_rows:
        ok = False
        print(f"[assert][FATAL] 恒等式不成立: Σ组={sum_groups} + 未分组={unassigned} "
              f"!= 总行数={n_rows}")
    else:
        print(f"[assert] 互不重叠 ✓  Σ组={sum_groups} + 未分组={unassigned} = {n_rows} ✓")
    manifest["coverage"] = {
        "rows": n_rows, "sum_groups": sum_groups, "unassigned": unassigned,
        "overlaps": overlaps,
        "identity_ok": (sum_groups + unassigned == n_rows and not overlaps),
        "per_group": {g: len(h) for g, h in group_hashes.items()},
    }
    # 提到顶层：打开 subsets_manifest.json 第一眼就能看到恒等式是否成立
    manifest["identity_ok"] = manifest["coverage"]["identity_ok"]
    manifest["rows"] = n_rows
    manifest["sum_groups"] = sum_groups
    manifest["unassigned"] = unassigned

    if a.dry_run:
        print("[dry-run] 未写任何文件")
        return 0 if ok else 1

    # ---- refusal scan report (§16) -----------------------------------------
    scan_groups = {}
    for gname, cats in groups.items():
        sel = SELECTORS.get(gname)
        if cats == ["*"] and sel is not None:
            # 行级判据组：cats 从未被回写进 groups，这里必须按 sel 反推，
            # 否则 by_cat.get("*") 恒为 0（曾导致 [refusal][forge] raw=0 的假数字）
            sel_rows = [r for r in uniq if sel(r)]
            sel_hashes = {r["_hash"] for r in sel_rows}
            sub = [d for h, d in refusal_hits.items() if h in sel_hashes]
            n_raw = len(sel_rows)
            cats = sorted({(r.get("meta") or {}).get("cat", "?") for r in sel_rows})
        else:
            sub = [d for _h, d in refusal_hits.items() if d["cat"] in cats]
            n_raw = sum(len(by_cat.get(c, [])) for c in cats)
        rate = len(sub) / max(1, n_raw)
        scan_groups[gname] = {
            "cats": cats, "raw": n_raw, "hits": len(sub), "rate": round(rate, 4),
            "verdict": "blocked" if rate > REFUSAL_BLOCK_RATE else "ok",
            "samples": [{k: d.get(k) for k in ("cat", "src", "match", "snippet")}
                        for d in sub[:20]],
        }
        print(f"[refusal][{gname}] raw={n_raw} hits={len(sub)} rate={rate * 100:.2f}% "
              f"→ {scan_groups[gname]['verdict']}"
              f"{'  （已剔除，可用于训练）' if a.filter_refusal else '  ⚠ 未剔除，不得用于训练'}")
    scan = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": os.path.abspath(a.data),
        "patterns": REFUSAL_PATTERNS,
        "block_rate_threshold": REFUSAL_BLOCK_RATE,
        "filter_enabled": bool(a.filter_refusal),
        "total_scanned": len(uniq), "total_hits": len(refusal_hits),
        "total_rate": round(len(refusal_hits) / max(1, len(uniq)), 4),
        "by_cat": {c: len(v) for c, v in sorted(ref_by_cat.items(), key=lambda kv: -len(kv[1]))},
        "groups": scan_groups,
        "judgement": "命中率 >2% 的子集不得用于训练；已设 --filter-refusal 时命中行已在切分前剔除",
    }
    if not a.dry_run:
        with open(os.path.join(a.out_dir, "refusal_scan.json"), "w", encoding="utf-8") as f:
            json.dump(scan, f, ensure_ascii=False, indent=2)
        manifest["refusal"] = {"total_scanned": len(uniq), "total_hits": len(refusal_hits),
                               "rate": scan["total_rate"], "filtered": bool(a.filter_refusal),
                               "report": "refusal_scan.json"}
        print(f"[refusal] 报告 → {os.path.join(a.out_dir, 'refusal_scan.json')}")

    with open(os.path.join(a.out_dir, "subsets_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(manifest['groups'])} 个子集 → {os.path.abspath(a.out_dir)}"
          f"（manifest: subsets_manifest.json）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
