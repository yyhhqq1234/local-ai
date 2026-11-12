#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_v5_mix.py —— V5（B 路径）训练集合流：主集 + 意愿层，按配比采样

来源与分类映射（**基于实测的 meta.cat 分布，属工程近似，不是官方定义**）：
  主集 data/large-mix-plus/train.jsonl  4388 行，字段 {messages, meta:{cat,tier,tool,action}}
     forge  ≈ tool-action + op-syntax + tool-route + kb-tool        （工具/语法/路由）
     re     ≈ kb-re + action-reverse + real-trajectory + trajectory （逆向知识与动作链）
     rest   ≈ reasoning + real-discipline + guard + transition-syntax
  意愿层（comply）：
     data/intent3/re-sft.messages.jsonl   120  W1 逆向意愿
     data/intent3/w3-bodies.jsonl         150  W3 露骨叙事（本机生成，见 gen_w3_bodies.py）
     data/intent3/w3n-negative.jsonl       30  W3n 负向对照
     data/intent3/w4-general.jsonl         80  W4 通用误拒
     （DPO 另走：data/intent2/compliance-dpo.jsonl 200 对，训练脚本需 dpo 模式，不混进 SFT）

配比（V5 方案 §13.4 的近似）：comply:3 / forge:4 / re:2 / rest:1
  → 以 comply 行数为基准 N，则 forge=4N/3、re=2N/3、rest=N/3（按可用量截断）

用法：
  python tools/build_v5_mix.py --dry-run          # 只统计，不写文件
  python tools/build_v5_mix.py                    # 写 data/intent3/v5-mix/train.jsonl + manifest
  python tools/build_v5_mix.py --seed 42 --ratio 3,4,2,1
"""
import argparse
import hashlib
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "data", "large-mix-plus", "train.jsonl")
COMPLY = [
    ("W1", os.path.join(ROOT, "data", "intent3", "re-sft.messages.jsonl")),
    ("W3", os.path.join(ROOT, "data", "intent3", "w3-bodies.jsonl")),
    ("W3n", os.path.join(ROOT, "data", "intent3", "w3n-negative.jsonl")),
    ("W4", os.path.join(ROOT, "data", "intent3", "w4-general.jsonl")),
]
OUTDIR = os.path.join(ROOT, "data", "intent3", "v5-mix")

FORGE_CATS = {"tool-action", "op-syntax", "tool-route", "kb-tool", "transition-syntax"}
RE_CATS = {"kb-re", "action-reverse", "real-trajectory", "trajectory"}
# 其余（reasoning / real-discipline / guard）归 rest


def fp(text, n=16):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def load_jsonl(p):
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def as_messages(rec):
    """统一成 {messages:[...]}，能转的转，转不了返回 None"""
    if isinstance(rec.get("messages"), list) and rec["messages"]:
        return rec["messages"]
    if rec.get("prompt") and rec.get("response"):
        return [{"role": "user", "content": rec["prompt"]},
                {"role": "assistant", "content": rec["response"]}]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--ratio", default="3,4,2,1", help="comply,forge,re,rest")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rnd = random.Random(a.seed)

    print("=== 1. 主集分类 ===")
    main_rows = load_jsonl(MAIN)
    buckets = {"forge": [], "re": [], "rest": []}
    for r in main_rows:
        cat = (r.get("meta") or {}).get("cat", "")
        b = "forge" if cat in FORGE_CATS else ("re" if cat in RE_CATS else "rest")
        buckets[b].append(r)
    for k, v in buckets.items():
        print(f"  {k:<6} {len(v):>5}")
    print(f"  total  {len(main_rows):>5}")

    print("=== 2. 意愿层 ===")
    comply_rows, comply_stat = [], {}
    for tag, p in COMPLY:
        rows = load_jsonl(p)
        ok = []
        for r in rows:
            ms = as_messages(r)
            if ms:
                ok.append({"messages": ms, "meta": {"group": tag, **(r.get("meta") or {})}})
        comply_stat[tag] = {"file": os.path.basename(p), "rows": len(rows), "usable": len(ok)}
        comply_rows.extend(ok)
        print(f"  {tag:<4} {len(ok):>4} usable / {len(rows)} rows  ({os.path.basename(p)})")
    print(f"  comply total {len(comply_rows)}")

    if not comply_rows:
        print("[FATAL] comply 为空 —— B 路径无法合流")
        return 2

    print("=== 3. 按配比采样 ===")
    w = [int(x) for x in a.ratio.split(",")]
    base = len(comply_rows)
    quota = {
        "comply": base,
        "forge": min(len(buckets["forge"]), round(base * w[1] / w[0])),
        "re": min(len(buckets["re"]), round(base * w[2] / w[0])),
        "rest": min(len(buckets["rest"]), round(base * w[3] / w[0])),
    }
    for k in ("forge", "re", "rest"):
        print(f"  {k:<6} {quota[k]:>5} / 可用 {len(buckets[k])}")

    picked = list(comply_rows)
    for k in ("forge", "re", "rest"):
        picked.extend(rnd.sample(buckets[k], quota[k]))

    print("=== 4. 去重与统计 ===")
    seen, final, dup = set(), [], 0
    for r in picked:
        h = fp(json.dumps(r["messages"], ensure_ascii=False))
        if h in seen:
            dup += 1
            continue
        seen.add(h)
        final.append(r)
    print(f"  picked={len(picked)} dedup_drop={dup} final={len(final)}")

    # token 份额（粗估：字符数 / 3.2 当 token）
    def approx_tok(r):
        return sum(len(m.get("content", "")) for m in r["messages"]) / 3.2
    tot = sum(approx_tok(r) for r in final) or 1
    share = {}
    for r in final:
        g = (r.get("meta") or {}).get("group") or "main"
        share[g] = share.get(g, 0) + approx_tok(r)
    print("  token 份额（近似）:")
    for g, v in sorted(share.items(), key=lambda kv: -kv[1]):
        print(f"    {g:<8} {v/tot*100:5.1f}%  ~{int(v):>7} tok")

    if a.dry_run:
        print("\n[dry-run] 不写文件")
        return 0

    os.makedirs(OUTDIR, exist_ok=True)
    outp = os.path.join(OUTDIR, "train.jsonl")
    with open(outp, "w", encoding="utf-8") as fo:
        for r in final:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")

    manifest = {
        "built_at": __import__("time").strftime("%F %T"),
        "seed": a.seed, "ratio": a.ratio,
        "main_source": os.path.relpath(MAIN, ROOT),
        "main_rows": len(main_rows),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "comply_sources": comply_stat,
        "comply_total": len(comply_rows),
        "quota": quota,
        "picked": len(picked), "dedup_drop": dup, "final": len(final),
        "token_share": {k: round(v / tot, 4) for k, v in share.items()},
        "out": os.path.relpath(outp, ROOT),
        "warning": "forge/re/rest 的分类是按 meta.cat 的工程近似，非官方定义；"
                   "DPO(compliance-dpo.jsonl 200 对)未混入本文件，需另走 dpo 模式",
    }
    mp = os.path.join(OUTDIR, "manifest.json")
    json.dump(manifest, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[out] {outp}")
    print(f"[out] {mp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
