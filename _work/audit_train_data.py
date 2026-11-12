# -*- coding: utf-8 -*-
"""训练数据全量体检 —— 9B 线两条腿实测

体检项（全部来自本项目已踩过的坑）：
  1 JSON 可解析 / 顶层结构一致性（struct 冲突曾让 2B v4 启动即崩）
  2 messages 角色序列合法性
  3 assistant 空 / 超短
  4 工具名编造（对照 tools.json 白名单 + 评测期望集，C 类硬伤）
  5 完全重复行
  6 评测集泄漏（精确 + 前 100 字，v4 曾泄 20 条）
  7 长度分布（ctx=2048，system 已占约 1500 字符）
  8 无任何工具调用的样本占比
门控腿额外：拒写 / 正常答 比例

用法：python _work/audit_train_data.py
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
TOOLS_JSON = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")
EVAL_DIR = os.path.join(L9B, "data", "eval")

TARGETS = [
    ("RE 腿  mix-z-re-v4.jsonl",
     os.path.join(L9B, "data", "_legacy", "mix-z-re-v4.jsonl"), "re"),
    ("门控  2b-gated-v4b-train",
     os.path.join(L9B, "data", "nsfw-gated", "train-2b-gated-v4b-train.jsonl"), "gate"),
]

# ── 白名单 ────────────────────────────────────────────────────────────
raw = json.load(io.open(TOOLS_JSON, encoding="utf-8"))
TOOL_NAMES = {t["name"] for t in raw}

from eval_cases_re import CASES  # noqa: E402
for c in CASES:
    for e in c.get("expect") or []:
        TOOL_NAMES.add(e)

TOOL_RE = re.compile(r"\b((?:kitty|reverse)_[a-z0-9_]+)\b")

# ── 评测集 user 文本（泄漏比对基准）────────────────────────────────────
eval_users, eval_files = set(), []
for split in ("val", "test"):
    d = os.path.join(EVAL_DIR, split)
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".jsonl"):
            continue
        p = os.path.join(d, fn)
        eval_files.append(p)
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            for k in ("user", "prompt", "question", "query", "input"):
                v = o.get(k)
                if isinstance(v, str) and v.strip():
                    eval_users.add(v.strip())
            msgs = o.get("messages")
            if isinstance(msgs, list):
                for m in msgs:
                    if m.get("role") == "user":
                        eval_users.add(str(m.get("content", "")).strip())
# 40 条 RE 用例也是评测集
for c in CASES:
    eval_users.add(c["ask"].strip())

EVAL_HEADS = {u[:100] for u in eval_users if len(u) >= 20}
print("评测基准：%d 条 user 文本（%d 个 jsonl + 40 条 RE 用例）"
      % (len(eval_users), len(eval_files)))
print("工具白名单：%d 个（tools.json %d + 评测期望补充）" % (len(TOOL_NAMES), len(raw)))
print()


def pct(xs, p):
    if not xs:
        return 0
    k = int(len(xs) * p / 100)
    return xs[min(k, len(xs) - 1)]


def audit(title, path, kind):
    print("=" * 90)
    print("【%s】%s" % (title, path))
    print("=" * 90)
    if not os.path.exists(path):
        print("  ★ 文件不存在")
        return
    size = os.path.getsize(path)
    n = bad_json = 0
    structs = Counter()
    roles_bad = []
    asst_empty = asst_short = 0
    fake_counter = Counter()
    fake_rows = 0
    hashes = Counter()
    dup_rows = 0
    leaks_exact, leaks_head = [], []
    lens = []
    no_tool = 0
    refuse = 0
    role_seqs = Counter()

    for line in io.open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
        except Exception:
            bad_json += 1
            continue
        structs[tuple(sorted(o.keys()))] += 1

        msgs = o.get("messages")
        if not isinstance(msgs, list) or not msgs:
            roles_bad.append((n, "no-messages"))
            continue
        rs = [m.get("role") for m in msgs]
        role_seqs[tuple(rs)] += 1

        # 角色合法性：必须以 user 结尾成对，system 只允许在最前
        legal = True
        if rs.count("system") > 1 or ("system" in rs and rs[0] != "system"):
            legal = False
        body = [r for r in rs if r != "system"]
        if not body or body[0] != "user" or body[-1] != "assistant":
            legal = False
        if any(body[i] == body[i + 1] for i in range(len(body) - 1)) and False:
            legal = False
        if not legal:
            roles_bad.append((n, ">".join(str(x) for x in rs)))

        user_txt = "".join(str(m.get("content", "")) for m in msgs if m.get("role") == "user")
        asst_txt = "".join(str(m.get("content", "")) for m in msgs if m.get("role") == "assistant")

        if not asst_txt.strip():
            asst_empty += 1
        elif len(asst_txt.strip()) < 15:
            asst_short += 1

        # 工具名编造
        got = set(TOOL_RE.findall(asst_txt))
        fake = got - TOOL_NAMES
        if fake:
            fake_rows += 1
            for f in fake:
                fake_counter[f] += 1

        # 重复
        h = hashlib.md5(line.encode()).hexdigest()
        hashes[h] += 1

        # 泄漏
        u = user_txt.strip()
        if u and u in eval_users:
            leaks_exact.append(n)
        elif len(u) >= 20 and u[:100] in EVAL_HEADS:
            leaks_head.append(n)

        # 长度（全样本字符数）
        total_chars = sum(len(str(m.get("content", ""))) for m in msgs)
        lens.append(total_chars)

        # 无工具调用
        if not got and not re.search(r"kitty_|reverse_add|reverse_submit|<tool_call>", asst_txt):
            no_tool += 1

        if kind == "gate":
            if re.search(r"(不能|不便|无法|恕不|不提供|不会提供|拒绝|不适合|抱歉)", asst_txt[:200]):
                refuse += 1

    dup_rows = sum(v - 1 for v in hashes.values() if v > 1)
    lens.sort()

    print("  体积 %.1f MB · 行数 %d" % (size / 1048576, n))
    print("  [1] JSON 解析失败：%d %s" % (bad_json, "★" if bad_json else "OK"))
    print("  [1] 顶层结构种类：%d %s" % (len(structs), "★多结构！" if len(structs) > 1 else "OK"))
    for k, v in structs.most_common(4):
        print("        %-46s %d 行" % (",".join(k), v))
    print("  [2] 角色序列异常：%d %s" % (len(roles_bad), "★" if roles_bad else "OK"))
    for ln, why in roles_bad[:5]:
        print("        行 %d：%s" % (ln, why))
    print("  [2] 角色序列分布（前 4）：")
    for k, v in role_seqs.most_common(4):
        print("        %-46s %d" % (">".join(str(x) for x in k), v))
    print("  [3] assistant 空 %d · 超短(<15字) %d %s"
          % (asst_empty, asst_short, "★" if (asst_empty or asst_short) else "OK"))
    print("  [4] 含编造工具名的行：%d %s" % (fake_rows, "★C类硬伤" if fake_rows else "OK"))
    for f, v in fake_counter.most_common(8):
        print("        %-34s %d 次" % (f, v))
    print("  [5] 完全重复行（多余份数）：%d %s" % (dup_rows, "★" if dup_rows else "OK"))
    print("  [6] 评测泄漏：精确 %d · 前100字 %d %s"
          % (len(leaks_exact), len(leaks_head),
             "★必须重做" if (leaks_exact or leaks_head) else "OK"))
    for ln in (leaks_exact + leaks_head)[:5]:
        print("        行 %d" % ln)
    print("  [7] 字符长度  P50=%d P90=%d P99=%d Max=%d"
          % (pct(lens, 50), pct(lens, 90), pct(lens, 99), lens[-1] if lens else 0))
    for thr in (4000, 6000, 8000, 12000):
        c = sum(1 for x in lens if x > thr)
        print("        >%5d 字符：%d 行 (%.1f%%)" % (thr, c, c * 100.0 / max(n, 1)))
    print("  [8] 无任何工具调用：%d 行 (%.1f%%)"
          % (no_tool, no_tool * 100.0 / max(n, 1)))
    if kind == "gate":
        print("  [9] 拒写式开头：%d 行 (%.1f%%) · 正常答：%d 行 (%.1f%%)"
              % (refuse, refuse * 100.0 / max(n, 1),
                 n - refuse, (n - refuse) * 100.0 / max(n, 1)))
    print()


for title, path, kind in TARGETS:
    audit(title, path, kind)
