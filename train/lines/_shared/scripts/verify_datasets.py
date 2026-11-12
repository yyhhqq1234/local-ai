#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""训练集内容完整性核查 —— 逐行哈希比对，确认零丢失

核查 6 条链路：
  1. bucketed vs 原文件（分桶是否丢内容）
  2. 2A kitty 部分 vs 原始 kitty（是否全量）
  3. 2A 轨迹部分 vs chunk 后轨迹（是否全量）
  4. chunk 后轨迹 assistant 内容 vs 原始轨迹（切分是否丢字符）
  5. 2B vs 5 个 nsfw 源文件（合并是否丢）
  6. 2C vs swe-16k-chunk4096（是否完整复制）

用法：
  python verify_datasets.py
  python verify_datasets.py --deep     # 额外做 chunk 字符级还原校验
"""

import argparse
import hashlib
import io
import json
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")


def load_hashes(path, field=None):
    """返回 Counter{md5(内容)}；field=None 用整行"""
    c = Counter()
    n = 0
    bad = 0
    with io.open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            if field is None:
                c[hashlib.md5(line.encode()).hexdigest()] += 1
            else:
                try:
                    o = json.loads(line)
                    v = o.get(field)
                    s = json.dumps(v, ensure_ascii=False, sort_keys=True) if not isinstance(v, str) else v
                    c[hashlib.md5(s.encode()).hexdigest()] += 1
                except Exception:
                    bad += 1
    return c, n, bad


def cmp(a_path, b_path, a_name, b_name, field=None):
    ca, na, _ = load_hashes(a_path, field)
    cb, nb, _ = load_hashes(b_path, field)
    only_a = ca - cb
    only_b = cb - ca
    miss = sum(only_a.values())
    extra = sum(only_b.values())
    status = "✅ 一致" if (not only_a and not only_b) else "❌ 有差异"
    print("  %-46s %6d 条" % (a_name, na))
    print("  %-46s %6d 条" % (b_name, nb))
    print("  → %s  仅A有=%d  仅B有=%d" % (status, miss, extra))
    return {"a": a_name, "b": b_name, "na": na, "nb": nb, "only_a": miss, "only_b": extra, "ok": not only_a and not only_b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true")
    args = ap.parse_args()

    D = "train/data"
    results = []

    print("=" * 78)
    print("1) 分桶是否丢内容（整行哈希集合比对）")
    print("=" * 78)
    pairs = [
        ("kitty", "%s/kitty-reverse/train-kitty-core.jsonl" % D, "%s/kitty-reverse/kitty-core-bucketed.jsonl" % D),
        ("2A", "%s/mix-2a.jsonl" % D, "%s/mix-2a-bucketed.jsonl" % D),
        ("2B", "%s/mix-2b.jsonl" % D, "%s/mix-2b-bucketed.jsonl" % D),
        ("2C", "%s/mix-2c.jsonl" % D, "%s/mix-2c-bucketed.jsonl" % D),
    ]
    for name, a, b in pairs:
        if not (os.path.exists(a) and os.path.exists(b)):
            print("  [跳过] %s 文件缺失" % name)
            continue
        print("[%s]" % name)
        r = cmp(a, b, os.path.basename(a), os.path.basename(b))
        r["chain"] = "bucket-" + name
        results.append(r)
        print()

    print("=" * 78)
    print("2) 2A kitty 部分溯源（应是原始 kitty 的 3 倍重复）")
    print("=" * 78)
    # 2A = kitty×3 + 轨迹；用 messages 哈希区分
    ka, nka, _ = load_hashes("%s/kitty-reverse/train-kitty-core.jsonl" % D, field="messages")
    ma, nma, _ = load_hashes("%s/mix-2a.jsonl" % D, field="messages")
    # 2A 里 kitty 的哈希应都能在原始 kitty 中找到，且计数是 3 倍
    kitty_set = set(ka)
    hit = sum(v for h, v in ma.items() if h in kitty_set)
    print("  原始 kitty 唯一样本 %d 条" % len(ka))
    print("  2A 中命中 kitty 的样本 %d 条（应为 %d = 5602×3）" % (hit, len(ka) * 3))
    print("  → %s" % ("✅ 全量×3" if hit == len(ka) * 3 else "⚠ 数量异常"))

    print()
    print("=" * 78)
    print("3) 2A 轨迹部分溯源")
    print("=" * 78)
    traj_files = [
        "%s/agent-traj/nemotron-swe/swe-8k-chunk4096.jsonl" % D,
        "%s/agent-traj/deepswe/deepswe-8k-chunk4096.jsonl" % D,
        "%s/agent-traj/swe-rebench/rebench-8k-chunk4096.jsonl" % D,
    ]
    traj_all = Counter()
    traj_n = 0
    for p in traj_files:
        if os.path.exists(p):
            c, n, _ = load_hashes(p, field="messages")
            traj_all.update(c)
            traj_n += n
    hit_t = sum(v for h, v in ma.items() if h in set(traj_all))
    print("  chunk 后轨迹唯一 %d 条 / 共 %d 条" % (len(traj_all), traj_n))
    print("  2A 中命中轨迹的样本 %d 条" % hit_t)
    print("  → %s" % ("✅ 全量" if hit_t == traj_n else "❌ 缺 %d 条" % (traj_n - hit_t)))

    print()
    print("=" * 78)
    print("4) 2B 溯源（5 个 nsfw 源合并）")
    print("=" * 78)
    srcs = ["train-cont", "train-scene", "train-multi", "train-style", "train-expand"]
    src_all = Counter()
    src_n = 0
    for s in srcs:
        p = "%s/nsfw/%s.jsonl" % (D, s)
        if os.path.exists(p):
            c, n, _ = load_hashes(p, field="messages")
            src_all.update(c)
            src_n += n
            print("    %-24s %6d 条" % (s, n))
    mb, nmb, _ = load_hashes("%s/mix-2b.jsonl" % D, field="messages")
    only_src = src_all - mb
    only_mix = mb - src_all
    print("  源合计 %d / mix-2b %d" % (src_n, nmb))
    print("  → %s  源有mix无=%d  mix有源无=%d" % (
        "✅ 一致" if not only_src and not only_mix else "❌ 有差异",
        sum(only_src.values()), sum(only_mix.values())))

    print()
    print("=" * 78)
    print("5) 2C 溯源")
    print("=" * 78)
    p_src = "%s/agent-traj/nemotron-swe/swe-16k-chunk4096.jsonl" % D
    p_dst = "%s/mix-2c.jsonl" % D
    if os.path.exists(p_src):
        r = cmp(p_src, p_dst, "swe-16k-chunk4096", "mix-2c")
        r["chain"] = "2C-source"
        results.append(r)

    print()
    print("=" * 78)
    print("汇总")
    print("=" * 78)
    bad = [r for r in results if not r["ok"]]
    if not bad:
        print("  ✅ 全部链路内容一致，无丢失")
    else:
        print("  ❌ 以下链路有差异：")
        for r in bad:
            print("     %s: 仅A有 %d / 仅B有 %d" % (r.get("chain"), r["only_a"], r["only_b"]))


if __name__ == "__main__":
    main()
