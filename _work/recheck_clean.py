# -*- coding: utf-8 -*-
"""清洗后复检：确认 F1/F2/F3 全部生效，且没有把数据集结构改坏

重点两件事：
  1 三项修复归零（污染 / 编造 / 重复）
  2 门控腿的「成对结构」有没有被去重破坏（同一 user 应出现 2 次：一拒一正常）
"""
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "train/lines/_shared/scripts")

L9B = "train/lines/9b-oxcoder"
GATE = os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train-deleak.jsonl")
RE = os.path.join(L9B, "data", "_legacy", "mix-z-re-v4-fixed.jsonl")
EVAL_DIR = os.path.join(L9B, "data", "eval")
TOOLS_JSON = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

raw = json.load(io.open(TOOLS_JSON, encoding="utf-8"))
TOOL_NAMES = {t["name"] for t in raw}
from eval_cases_re import CASES  # noqa: E402
for c in CASES:
    for e in c.get("expect") or []:
        TOOL_NAMES.add(e)
TOOL_RE = re.compile(r"\b((?:kitty|reverse)_[a-z0-9_]+)\b")
REFUSE_RE = re.compile(r"(不能|不便|无法|恕不|不提供|不会提供|拒绝|抱歉|不适合)")


def users_of(o):
    return [str(m.get("content", "")).strip() for m in o.get("messages", [])
            if m.get("role") == "user"]


def ustr(o):
    return "".join(users_of(o)).strip()


def asst_of(o):
    return "".join(str(m.get("content", "")) for m in o.get("messages", [])
                   if m.get("role") == "assistant")


poison = set()
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        for line in io.open(os.path.join(d, fn), encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            for u in users_of(o):
                if len(u) >= 20:
                    poison.add(u[:100])

print("评测头部基准 %d 种" % len(poison))
print()


def check(title, path, expect_n, gate=False):
    print("=" * 88)
    print("【%s】%s" % (title, os.path.basename(path)))
    print("=" * 88)
    n = leak = fake = 0
    hashes = Counter()
    user_cnt = Counter()
    refuse = 0
    lens = []
    fake_detail = Counter()
    trunc_detail = Counter()
    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        n += 1
        o = json.loads(line)
        u = ustr(o)
        if u and any(len(x) >= 20 and x[:100] in poison for x in users_of(o)):
            leak += 1
        a = asst_of(o)
        bad = set(TOOL_RE.findall(a)) - TOOL_NAMES
        # 以 _ 结尾的（reverse_add_* / kitty_rea_…）是通配符或省略写法，不算编造
        real = {x for x in bad if not x.endswith("_")}
        for x in bad - real:
            trunc_detail[x] += 1
        if real:
            fake += 1
            for x in real:
                fake_detail[x] += 1
        hashes[hashlib.md5(line.encode()).hexdigest()] += 1
        user_cnt[u] += 1
        if gate and REFUSE_RE.search(a[:200]):
            refuse += 1
        lens.append(sum(len(str(m.get("content", ""))) for m in o["messages"]))

    dup = sum(v - 1 for v in hashes.values() if v > 1)
    lens.sort()
    print("  行数 %d %s" % (n, "OK" if n == expect_n else "★期望 %d" % expect_n))
    print("  [F1] 评测污染：%d  %s" % (leak, "✅ 归零" if leak == 0 else "★残留"))
    print("  [F2] 真编造工具名：%d  %s" % (fake, "✅ 归零" if fake == 0 else "★残留"))
    if fake_detail:
        for x, c in fake_detail.most_common(10):
            print("        ★ %-28s %d 次" % (x, c))
    if trunc_detail:
        print("        （通配/截断写法，非编造：%s）"
              % ", ".join("%s×%d" % (k, v) for k, v in trunc_detail.most_common(6)))
    print("  [F3] 完全重复（多余份数）：%d  %s" % (dup, "✅ 归零" if dup == 0 else "★残留"))
    print("  长度 P50=%d P99=%d Max=%d" % (lens[len(lens) // 2], lens[int(len(lens) * .99)], lens[-1]))
    if gate:
        dist = Counter(user_cnt.values())
        print("  同 user 行数分布：%s" % dict(sorted(dist.items())[:6]))
        pair = dist.get(2, 0)
        single = dist.get(1, 0)
        print("  └─ 出现 2 次（成对拒/答）：%d 个 user · 出现 1 次：%d 个" % (pair, single))
        print("  拒写式开头：%d (%.1f%%) · 其余 %.1f%%"
              % (refuse, refuse * 100.0 / n, 100 - refuse * 100.0 / n))
    else:
        print("  同 user 行数分布：%s" % dict(sorted(Counter(user_cnt.values()).items())[:5]))
    print()


check("门控腿 deleak", GATE, 28967, gate=True)
check("RE 腿 fixed", RE, 7562, gate=False)
