# -*- coding: utf-8 -*-
"""make_comply_subsets.py —— 把 compliance-sft.jsonl（400）按 seed 分层切成
comply-subset.train.jsonl(320) / comply-subset.val.jsonl(80)

命名与哈希严格对齐现有链路：
  · 文件名满足 precompute_activations 的 glob  `^(.+)-subset\\.(train|val)\\.jsonl$`
  · 分组 key 用 make_subsets.content_hash（同一 6 行算法）—— 否则 split map 整片 miss

断言（不过就退出非 0）：
  1) 每类 100 → train 80 / val 20
  2) train 与 val 的 content_hash 不相交
  3) 400 条 prompt 全局唯一（同 prompt 只允许一个答案）
"""
import argparse
import collections
import hashlib
import io
import json
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "intent2", "compliance-sft.jsonl")
OUT = os.path.join(BASE, "data", "intent2")


def content_hash(row):
    """与 make_subsets.content_hash 逐字一致（precompute 也镜像了这段）"""
    msgs = row.get("messages") or []
    norm = [{"role": m.get("role", ""), "content": (m.get("content") or "").strip()}
            for m in msgs]
    blob = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sh16(p):
    b = open(p, "rb").read()
    return hashlib.sha256(b).hexdigest()[:16], len(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-ratio", type=float, default=0.2)
    args = ap.parse_args()

    rows = [json.loads(l) for l in io.open(SRC, encoding="utf-8") if l.strip()]
    for r in rows:
        r["_hash"] = content_hash(r)

    # 断言 3：prompt 全局唯一
    prompts = collections.Counter(r["messages"][0]["content"] for r in rows)
    dup_prompt = {p: c for p, c in prompts.items() if c > 1}
    # 顺带查「同 prompt 不同答案」（即便 prompt 唯一，也确认一遍）
    by_prompt = collections.defaultdict(set)
    for r in rows:
        by_prompt[r["messages"][0]["content"]].add(r["messages"][1]["content"])
    conflict = {p: len(v) for p, v in by_prompt.items() if len(v) > 1}

    rng = random.Random(args.seed)
    by_cat = collections.defaultdict(list)
    for r in rows:
        by_cat[r["meta"]["cat"]].append(r)

    train, val = [], []
    per_cat = {}
    for cat in sorted(by_cat):
        lst = list(by_cat[cat])
        rng.shuffle(lst)
        n_val = max(1, int(round(len(lst) * args.val_ratio)))
        val.extend(lst[:n_val])
        train.extend(lst[n_val:])
        per_cat[cat] = {"total": len(lst), "train": len(lst) - n_val, "val": n_val}

    # 断言 2：不相交
    leak = {r["_hash"] for r in train} & {r["_hash"] for r in val}

    os.makedirs(OUT, exist_ok=True)
    p_tr = os.path.join(OUT, "comply-subset.train.jsonl")
    p_va = os.path.join(OUT, "comply-subset.val.jsonl")
    for path, subset in ((p_tr, train), (p_va, val)):
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in subset:
                r2 = {k: v for k, v in r.items() if not k.startswith("_")}
                f.write(json.dumps(r2, ensure_ascii=False) + "\n")

    tr_h, tr_b = sh16(p_tr)
    va_h, va_b = sh16(p_va)
    ok = (not leak) and (not dup_prompt) and (not conflict) and \
         len(train) == 320 and len(val) == 80 and \
         all(v["train"] == 80 and v["val"] == 20 for v in per_cat.values())

    man = {
        "generated_by": "scripts/make_comply_subsets.py",
        "source": "data/intent2/compliance-sft.jsonl",
        "source_rows": len(rows),
        "seed": args.seed, "val_ratio": args.val_ratio,
        "hash_algo": "make_subsets.content_hash（json.dumps(norm, ensure_ascii=False, sort_keys=True)）",
        "per_cat": per_cat,
        "train": {"file": "comply-subset.train.jsonl", "rows": len(train),
                  "sha16": tr_h, "bytes": tr_b},
        "val": {"file": "comply-subset.val.jsonl", "rows": len(val),
                "sha16": va_h, "bytes": va_b},
        "assertions": {
            "train_val_hash_disjoint": not leak,
            "leak_count": len(leak),
            "prompt_unique": not dup_prompt,
            "dup_prompt": dup_prompt,
            "same_prompt_diff_answer": conflict,
            "counts_ok": len(train) == 320 and len(val) == 80,
            "verdict": "PASS" if ok else "FAIL",
        },
    }
    with io.open(os.path.join(OUT, "COMPLY-SUBSET-MANIFEST.json"), "w",
                 encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=2)

    print(json.dumps({k: man[k] for k in ("per_cat", "train", "val")}, ensure_ascii=False, indent=1))
    print("assertions:", json.dumps(man["assertions"], ensure_ascii=False))
    print("Verdict:", man["assertions"]["verdict"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
