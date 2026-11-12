#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""重配前探测：配对关系 / 素材池 / ctl 可用源"""
import json, os, collections, hashlib

BASE = r"train/lines/9b-oxcoder/data"
GATED = os.path.join(BASE, "nsfw-gated", "train-2b-gated.jsonl")

def load(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out

rows = load(GATED)
def suf(r):
    i = r.get("id", "")
    return i.rsplit("#", 1)[-1] if "#" in i else ""

def usr(r):
    for m in r.get("messages", []):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""

pos = [r for r in rows if suf(r) == "pos"]
neg = [r for r in rows if suf(r) == "neg0"]
ctl = [r for r in rows if suf(r) == "ctl"]

def h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:12]

ph = set(h(usr(r)) for r in pos)
nh = set(h(usr(r)) for r in neg)
print("pos", len(pos), "neg", len(neg), "ctl", len(ctl))
print("pos uniq user", len(ph), "neg uniq user", len(nh))
print("neg user 命中 pos 池:", len(nh & ph), "/", len(nh))
print("neg 的 user 也出现在 pos 里但 id 不同 —— 说明是同一素材池分别抽取")

# 开关词提取规则探测：neg 的 user 是否含开关词
import re
TRIG = re.compile(r"(\[\[模式:NSFW\]\]|\[\[NSFW\]\]|\[NSFW\]|NSFW|成人内容|R18|无限制模式|成人向创作模式|18\+\s*模式)")
cnt = collections.Counter()
for r in neg[:2000]:
    m = TRIG.search(usr(r))
    cnt[m.group(0) if m else "(none)"] += 1
print("\nneg 前2000条 user 含开关词:", dict(cnt))

# 可用 ctl 源
CAND = [
    (os.path.join(BASE, "kitty-reverse", "train-kitty-v3-clean.jsonl"), "kitty-rev"),
    (os.path.join(BASE, "agent-traj", "traj-2a-lite.jsonl"), "2a-traj"),
    (os.path.join(BASE, "nsfw-gated", "gate-pos.jsonl"), "gate-pos"),
    (os.path.join(BASE, "nsfw-gated", "gate-neg.jsonl"), "gate-neg"),
]
print("\n=== ctl 候选源 ===")
for p, tag in CAND:
    if os.path.exists(p):
        n = sum(1 for _ in open(p, encoding="utf-8"))
        print(f"  OK   {tag:<10} {n:7d} 行  {os.path.getsize(p)/1e6:7.1f} MB  {p}")
    else:
        print(f"  MISS {tag:<10} {p}")

# 看一个 kitty 样本形态（能否直接当 ctl）
kp = os.path.join(BASE, "kitty-reverse", "train-kitty-v3-clean.jsonl")
if os.path.exists(kp):
    with open(kp, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 1:
                break
            d = json.loads(line)
            print("\n=== kitty-v3-clean 样本 ===")
            print("keys", list(d.keys()))
            for m in d.get("messages", []):
                print(f"  {m['role']:>9}: {(m.get('content') or '')[:200]!r}")
