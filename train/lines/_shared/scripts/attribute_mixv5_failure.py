#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""缺陷归因：量化「8% rehearsal」这个前提是否成立，以及 2A 侧 cov 掉点的数据机制。

三个要回答的问题：
  Q1 方案 Y 说的「2A 占 8%」，是按**行数**算的；按**token/字符**算是多少？
     （loss 是 completion_only，按 token 加权 —— 所以真正决定梯度的是 token 份额，不是行份额）
  Q2 2A 训练数据的「标识符密度」vs kitty 数据 vs 2A 评测期望，谁在拉低 avg_cov？
  Q3 2A 训练数据的答案长度与评测期望是否错位（裁剪 600-1600 的副作用）
"""
import io
import json
import os
import re
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # train/
MIX = os.path.join(ROOT, "data", "mix-v5.jsonl")
CORE = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-bucketed.jsonl")
TRAJ = os.path.join(ROOT, "data", "agent-traj", "traj-2a-v4-aug.jsonl")

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def userof(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "user")


def scan(path, tag):
    n = 0
    a_chars = 0
    u_chars = 0
    a_len = []
    id_per_1k = []
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        a = asst(o)
        u = userof(o)
        n += 1
        a_chars += len(a)
        u_chars += len(u)
        a_len.append(len(a))
        ids = set(IDENT.findall(a))
        if a:
            id_per_1k.append(1000.0 * len(ids) / len(a))
    return dict(tag=tag, n=n, a_chars=a_chars, u_chars=u_chars, a_len=a_len,
                id_per_1k=id_per_1k)


def pct(v, p):
    v = sorted(v)
    if not v:
        return 0
    k = (len(v) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


print("=" * 92)
print("Q1  share by ROWS vs by CHARACTERS（loss 按 token 加权 ⇒ 字符份额才是梯度份额）")
print("=" * 92)
k = scan(CORE, "kitty")
t = scan(TRAJ, "2a")
tot_n = k["n"] + t["n"]
tot_c = k["a_chars"] + t["a_chars"]
print("  %-8s %8s %12s %12s %10s %10s" % ("源", "行数", "assistant字符", "user字符", "行份额", "assistant字符份额"))
for s in (k, t):
    print("  %-8s %8d %12d %12d %9.2f%% %13.2f%%"
          % (s["tag"], s["n"], s["a_chars"], s["u_chars"],
             100.0 * s["n"] / tot_n, 100.0 * s["a_chars"] / tot_c))
print("  => 方案 Y 的 8%% 是行份额 %.2f%%；而 assistant 字符份额 = %.2f%%"
      % (100.0 * t["n"] / tot_n, 100.0 * t["a_chars"] / tot_c))
print("  => completion_only 的 loss 只在 assistant 段计算 => 真正决定梯度的是字符份额")

print("")
print("=" * 92)
print("Q2  assistant 长度与「标识符密度」对比")
print("=" * 92)
print("  %-8s %8s %8s %8s %14s %14s" % ("源", "P50", "P90", "mean", "标识符/千字符P50", "标识符/千字符mean"))
for s in (k, t):
    m = statistics.mean(s["id_per_1k"])
    print("  %-8s %8d %8d %8d %14.2f %14.2f"
          % (s["tag"], pct(s["a_len"], .5), pct(s["a_len"], .9),
             statistics.mean(s["a_len"]), pct(s["id_per_1k"], .5), m))

print("")
print("=" * 92)
print("Q3  2A 评测期望的 must_mention 数量 vs 训练答案能提供的标识符量")
print("=" * 92)
import sys
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from eval_cases_2a import CASES as A2
mm = [len(c.get("must_mention") or []) for c in A2]
print("  40 条评测题：must_mention 条数 mean %.2f  P50 %d  max %d  合计 %d"
      % (statistics.mean(mm), pct(mm, .5), max(mm), sum(mm)))
print("  训练集 2A 每条 assistant 的解释：长度 P50 %d 字符、标识符 P50 %.1f 个/千字符"
      % (pct(t["a_len"], .5), pct(t["id_per_1k"], .5)))
