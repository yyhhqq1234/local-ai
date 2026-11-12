#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""audit_gen2_data.py —— gen2 训练集质量审计（纯 CPU，不碰 GPU）

检查项：
  1 门控成对性：nlsw-gated 的 #neg 行，能否在同集里找到"同一请求 + 触发词"的 pos 行
  2 触发词分布 / 类别分布
  3 完全重复与近似重复（13-gram shingle Jaccard ≥0.9）
  4 与 val/test 的泄漏（精确相同 + 13-gram 命中）
  5 token 长度分布（p50/p90/p99）与超长样本计数
用法：python audit_gen2_data.py [--data ...] [--val ...] [--test ...]
"""
import argparse
import hashlib
import json
import os
import re
import sys

TRAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(TRAIN, "data", "versions", "gen2-nsfw-kitty.20261029-003831.jsonl")
DEFAULT_VAL = os.path.join(TRAIN, "data", "eval", "val")
DEFAULT_TEST = os.path.join(TRAIN, "data", "eval", "test")

TRIGGERS = ["[[NSFW]]", "[NSFW]", "NSFW", "成人内容", "R18", "18+", "无限制模式", "成人向创作模式", "模式:NSFW"]


def norm(t):
    return re.sub(r"\s+", "", t or "")


def shingles(t, k=13):
    t = norm(t)
    return {t[i:i + k] for i in range(max(0, len(t) - k + 1))}


def msgs_text(obj):
    return "\n".join(str(m.get("content", "")) for m in obj.get("messages") or [])


def load(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--val", default=DEFAULT_VAL)
    ap.add_argument("--test", default=DEFAULT_TEST)
    a = ap.parse_args()

    rows = load(a.data)
    print(f"[data] {os.path.basename(a.data)}: {len(rows)} 行")

    # 1 门控成对性
    users = {}
    negs = []
    for r in rows:
        rid = str(r.get("id", ""))
        u = next((m.get("content") for m in r.get("messages") or [] if m.get("role") == "user"), "")
        if "#neg" in rid:
            negs.append((rid, u))
        else:
            users.setdefault(norm(u), rid)
    paired = sum(1 for _, u in negs if norm(u) in users)
    print(f"[pair] neg={len(negs)} 能在 pos 里找到同请求的 = {paired} "
          f"({paired/max(len(negs),1)*100:.1f}%)  ← 门控要求接近 100%")

    # 2 触发词/类别
    trig = {t: 0 for t in TRIGGERS}
    for r in rows:
        rid = str(r.get("id", ""))
        if "#neg" in rid:
            continue
        txt = msgs_text(r)[:2000]
        for t in TRIGGERS:
            if t in txt:
                trig[t] += 1
                break
    print("[trig] pos 行触发词命中:", {k: v for k, v in trig.items() if v})
    print(f"       未命中任何触发词的 pos 行 = {trig.get('_none', 0) or (len(rows)-len(negs)-sum(trig.values()))}")

    # 3 重复
    exact, sh = {}, {}
    dup_exact = dup_near = 0
    for r in rows:
        t = msgs_text(r)
        h = hashlib.sha1(norm(t).encode()).hexdigest()
        if h in exact:
            dup_exact += 1
        exact[h] = 1
        s = shingles(t)
        if not s:
            continue
        hit = False
        for k in list(sh)[:0]:
            pass
        # 用最小 shingle 做桶，避免 O(n^2)
        key = min(s)
        cand = sh.get(key, [])
        for other in cand:
            inter = len(s & other)
            if inter / max(len(s | other), 1) >= 0.9:
                dup_near += 1
                hit = True
                break
        if not hit:
            sh.setdefault(key, []).append(s)
    print(f"[dup] 完全重复 {dup_exact} | 近似重复(Jaccard≥0.9) {dup_near}")

    # 4 与 val/test 泄漏
    for tag, d in (("val", a.val), ("test", a.test)):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            er = load(os.path.join(d, fn))
            eh = {hashlib.sha1(norm(msgs_text(x)).encode()).hexdigest() for x in er}
            es = set()
            for x in er:
                es |= shingles(msgs_text(x))
            hit_exact = sum(1 for r in rows if hashlib.sha1(norm(msgs_text(r)).encode()).hexdigest() in eh)
            hit_near = 0
            for r in rows:
                s = shingles(msgs_text(r))
                if s and len(s & es) / max(len(s), 1) > 0.8:
                    hit_near += 1
            print(f"[leak] {tag}/{fn}: {len(er)} 条 → 训练集精确命中 {hit_exact} / 近似命中 {hit_near}")

    # 5 长度
    lens = sorted(len(msgs_text(r)) for r in rows)
    if lens:
        q = lambda p: lens[int(len(lens) * p)]
        print(f"[len] chars p50={q(.5)} p90={q(.9)} p99={q(.99)} max={lens[-1]} >8000 字符={sum(1 for x in lens if x>8000)}")


if __name__ == "__main__":
    main()
