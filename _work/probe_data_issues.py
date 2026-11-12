# -*- coding: utf-8 -*-
"""定性 probe：把体检出的四类问题逐条摊开

  1 门控腿 15 条「前100字重合」到底是真泄漏还是误报
  2 编造工具名的具体上下文（RE 20 行 / 门控 8 行）
  3 RE 腿 4 种顶层结构各是什么（meta / _aug / _coverage 会不会进训练）
  4 RE 腿「无工具调用」样本抽样（25.4% 是否真稀释）
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "train/lines/_shared/scripts")

L9B = "train/lines/9b-oxcoder"
TOOLS_JSON = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")
EVAL_DIR = os.path.join(L9B, "data", "eval")
RE = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4.jsonl")
GATE = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train.jsonl")

raw = json.load(io.open(TOOLS_JSON, encoding="utf-8"))
TOOL_NAMES = {t["name"] for t in raw}
from eval_cases_re import CASES  # noqa: E402
for c in CASES:
    for e in c.get("expect") or []:
        TOOL_NAMES.add(e)
TOOL_RE = re.compile(r"\b((?:kitty|reverse)_[a-z0-9_]+)\b")

# eval 基准：head(100) -> [(文件, 原文)]
head2src = {}
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        p = os.path.join(d, fn)
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            txts = []
            for k in ("user", "prompt", "question", "query", "input"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    txts.append(v.strip())
            msgs = o.get("messages")
            if isinstance(msgs, list):
                for m in msgs:
                    if m.get("role") == "user":
                        txts.append(str(m.get("content", "")).strip())
            for t in txts:
                if len(t) >= 20:
                    head2src.setdefault(t[:100], []).append(("%s/%s" % (split, fn), t))
for c in CASES:
    t = c["ask"].strip()
    if len(t) >= 20:
        head2src.setdefault(t[:100], []).append(("eval_cases_re/%s" % c["id"], t))


def user_of(o):
    return "".join(str(m.get("content", "")) for m in o.get("messages", [])
                   if m.get("role") == "user").strip()


def asst_of(o):
    return "".join(str(m.get("content", "")) for m in o.get("messages", [])
                   if m.get("role") == "assistant")


print("#" * 92)
print("# 1) 门控腿「前100字重合」定性")
print("#" * 92)
n = 0
for lineno, line in enumerate(io.open(GATE, encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    u = user_of(o)
    if len(u) >= 20 and u[:100] in head2src:
        n += 1
        if n > 8:
            continue
        src, orig = head2src[u[:100]][0]
        print("-" * 92)
        print("行 %d  ← 命中 %s" % (lineno, src))
        print("  训练 user(前160): %s" % u[:160].replace("\n", "⏎"))
        print("  评测 user(前160): %s" % orig[:160].replace("\n", "⏎"))
        print("  完全相同: %s | 训练长度 %d / 评测长度 %d"
              % (u == orig, len(u), len(orig)))
print("... 共 %d 条" % n)

print()
print("#" * 92)
print("# 2) 编造工具名上下文")
print("#" * 92)
for tag, path in (("RE", RE), ("GATE", GATE)):
    cnt = 0
    for lineno, line in enumerate(io.open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        a = asst_of(o)
        fake = set(TOOL_RE.findall(a)) - TOOL_NAMES
        if not fake or cnt >= 6:
            continue
        cnt += 1
        print("-" * 92)
        print("[%s] 行 %d 编造=%s" % (tag, lineno, sorted(fake)))
        for f in sorted(fake):
            i = a.find(f)
            print("   …%s…" % a[max(0, i - 70):i + 90].replace("\n", "⏎"))

print()
print("#" * 92)
print("# 3) RE 腿 4 种顶层结构样本")
print("#" * 92)
seen = {}
for line in io.open(RE, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    k = tuple(sorted(o.keys()))
    if k in seen:
        continue
    seen[k] = o
    print("-" * 92)
    print("keys = %s" % (k,))
    for kk in k:
        if kk == "messages":
            print("   messages: %d 条 · system 长度 %d"
                  % (len(o["messages"]),
                     len(str(o["messages"][0].get("content", ""))) if o["messages"] and o["messages"][0].get("role") == "system" else 0))
        elif kk in ("meta", "_aug", "_coverage"):
            print("   %-10s = %s" % (kk, json.dumps(o[kk], ensure_ascii=False)[:220]))

print()
print("#" * 92)
print("# 4) RE 腿「无工具调用」抽样（前 6 条）")
print("#" * 92)
cnt = 0
for lineno, line in enumerate(io.open(RE, encoding="utf-8"), 1):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line)
    a = asst_of(o)
    if TOOL_RE.findall(a) or re.search(r"kitty_|reverse_add|reverse_submit|<tool_call>", a):
        continue
    if cnt >= 6:
        break
    cnt += 1
    u = user_of(o)
    print("-" * 92)
    print("行 %d | user: %s" % (lineno, u[:130].replace("\n", "⏎")))
    print("        asst: %s" % a[:230].replace("\n", "⏎"))
