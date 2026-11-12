#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按长度分桶重排 -- 消除变长样本导致的显存碎片

问题（2026-10-28 实测）：
  kitty 前 47 步样本长度都在 200-228 token，分配器能一直复用显存块；
  第 48 步遇到 429 token 的样本，需要约 2 倍大小的连续块 →
  Windows WDDM 无 expandable_segments，碎片无法回收 → 分页抖动 →
  单步从 2.49s 掉到 68-124s，且不可恢复。

做法：
  按 token 长度分桶（默认 128 token 一档），桶内用固定种子打乱，
  桶间按长度递增排列。这样相邻样本长度接近，显存分配尺寸稳定，
  既消除碎片，又保留桶内随机性。

用法：
  python bucket_by_length.py --in f.jsonl --out g.jsonl --bucket 128
"""

import argparse
import io
import json
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--bucket", type=int, default=128, help="桶宽（token）")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer)

    rows = []
    with io.open(args.inp, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            msgs = o.get("messages")
            if not isinstance(msgs, list):
                continue
            t = sum(len(tok.encode(m["content"], add_special_tokens=False)) for m in msgs) + 64
            rows.append((t, line))

    print("样本 %d 条，长度 min=%d max=%d" % (len(rows), min(r[0] for r in rows), max(r[0] for r in rows)))

    # 分桶
    buckets = {}
    for t, line in rows:
        b = t // args.bucket
        buckets.setdefault(b, []).append(line)

    rng = random.Random(args.seed)
    out = []
    for b in sorted(buckets):
        grp = buckets[b]
        rng.shuffle(grp)
        out.extend(grp)

    with io.open(args.out, "w", encoding="utf-8") as f:
        for line in out:
            f.write(line + "\n")

    print("桶数 %d，已写出 %d 条 → %s" % (len(buckets), len(out), args.out))
    # 打印桶分布
    ks = sorted(buckets)
    print("桶分布(前12)：")
    for b in ks[:12]:
        print("  [%4d-%4d tok] %5d 条" % (b * args.bucket, (b + 1) * args.bucket - 1, len(buckets[b])))
    if len(ks) > 12:
        print("  ... 共 %d 个桶" % len(ks))


if __name__ == "__main__":
    main()
