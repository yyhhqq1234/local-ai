#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mix_reasoning.py —— 把推理链数据按配比混入主训练集

用法:
  python mix_reasoning.py --base data/large --reason data/reasoning --ratio 0.3 --out data/large-mix
  python mix_reasoning.py --dry-run --ratio 0.3

规则:
  · 只取 --reason 目录下 *.jsonl，排除：_ 前缀、*test*、seeds*
  · 与 base 按「user 前 40 字」去重（同一道题不进两次）
  · token 超 1500：可 --truncate 保头尾，否则丢弃
  · 配比按最终总量算：n_reason = len(base) * ratio / (1 - ratio)
  · eval / dpo 原样复制，保证训练脚本路径不变
"""
import argparse
import json
import os
import random

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CJK = __import__("re").compile(r"[\u4e00-\u9fa5]")


def est_tokens(t):
    c = len(CJK.findall(t))
    return int(c + (len(t) - c) * 0.27)


def jlines(p):
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def headtail(text, budget):
    if est_tokens(text) <= budget:
        return text
    ratio = budget / max(1, est_tokens(text))
    keep = int(len(text) * ratio)
    return text[: int(keep * 0.65)] + "\n…（中段已省略）…\n" + text[-int(keep * 0.35):]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.path.join(HERE, "data", "large"))
    ap.add_argument("--reason", default=os.path.join(HERE, "data", "reasoning"))
    ap.add_argument("--ratio", type=float, default=0.3)
    ap.add_argument("--out", default=os.path.join(HERE, "data", "large-mix"))
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--truncate", action="store_true")
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base_path = os.path.join(a.base, "train.jsonl")
    base = jlines(base_path)
    if not base:
        print(f"[FATAL] base 为空：{base_path}")
        return 2

    files = []
    if os.path.isdir(a.reason):
        for f in sorted(os.listdir(a.reason)):
            low = f.lower()
            if not low.endswith(".jsonl") or low.startswith("_") or "test" in low or "seeds" in low:
                continue
            files.append(os.path.join(a.reason, f))
    reason = []
    for p in files:
        reason += jlines(p)
    print(f"[input] base={len(base)} reason_files={len(files)} reason_rows={len(reason)}")

    seen = {r["messages"][0]["content"][:40] for r in base if r.get("messages")}
    pool, dropped_tok, dropped_dup = [], 0, 0
    for r in reason:
        msgs = r.get("messages") or []
        if not msgs:
            continue
        key = msgs[0]["content"][:40]
        if key in seen:
            dropped_dup += 1
            continue
        seen.add(key)
        est = est_tokens("\n".join(m["content"] for m in msgs))
        if est > a.max_tokens:
            if not a.truncate:
                dropped_tok += 1
                continue
            msgs[-1]["content"] = headtail(msgs[-1]["content"], max(300, a.max_tokens - est_tokens(msgs[0]["content"]) - 50))
        r.setdefault("meta", {})["cat"] = r["meta"].get("cat", "reasoning")
        pool.append(r)

    n_reason = min(len(pool), int(len(base) * a.ratio / max(1e-6, 1 - a.ratio)))
    random.Random(a.seed).shuffle(pool)
    picked = pool[:n_reason]
    train = base + picked
    random.Random(a.seed).shuffle(train)

    summary = {"base": len(base), "reason_files": len(files), "reason_rows": len(reason),
               "dropped_dup": dropped_dup, "dropped_tok": dropped_tok,
               "picked_reason": len(picked), "final_train": len(train),
               "ratio": round(len(picked) / max(1, len(train)), 3)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if a.dry_run:
        print("[dry-run] 未落盘")
        return 0

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "train.jsonl"), "w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for name in ("eval.jsonl", "dpo.jsonl"):
        src = os.path.join(a.base, name)
        if os.path.isfile(src):
            dst = os.path.join(a.out, name)
            with open(src, "r", encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
                fo.write(fi.read())
    json.dump(summary, open(os.path.join(a.out, "mix-manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[ok] → {a.out} (train={len(train)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
