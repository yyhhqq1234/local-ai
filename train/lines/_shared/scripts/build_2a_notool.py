#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_2a_notool.py — P0① 造「评测形态 + 禁工具」的 2A 训练样本

## 缺陷依据（2026-10-30，见 train/logs/mix-v5-FAILURE-ANALYSIS.md）

mix-v5 的 2A 答卷 16/40 吐了 `<tool_call>`，这 16 题 Δcov **−0.448**、无一例变好；
没吐的 24 题 Δcov **+0.107**。全部净亏损由泄漏造成。
两个数据侧原因：

① 输入形态错位：训练 user 是抽象 issue（2001 条里仅 57 条提到具体文件名，2.9%），
   评测 user 全部是「具体文件 + 具体函数 + 触发值」⇒ 模型遇到陌生形态就退回 `<tool_call>`。
② 无负例：kitty 段 900 行 `<tool_call>` 正例，2A 段 0 行「不许调工具」的示范。

## 源数据质量闸门（本次实测，决定了产物形态）

原 `traj-2a-v4-aug.jsonl` 2001 行：
    含 def/class        330（16.5%）
    含文件路径         1719（85.9%）
    叙述/片段开头       834（41.7%）   ← "## Phase 8: FINAL REVIEW"、"4. Observe…" 这类
    严格合格（def+file+干净开头）**162（8.1%）**
⇒ 不能无条件改写：那会造出「`missing_branches` 里的 `covered_branches` 出问题了」这种伪关系。
   因此分两档，**只允许真实存在的关系进 prompt**：

   T1 strict  : file + def/class + 干净开头  → prompt 写「`file` 里的 `func()` …」
   T2 fileonly: file + 干净开头（无 def）      → prompt 只写「`file` …」，不编函数名

## 用法
  python train/lines/_shared/scripts/build_2a_notool.py --tier t1
  python train/lines/_shared/scripts/build_2a_notool.py --tier t2 --n 700
"""
import argparse
import io
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "agent-traj", "traj-2a-v4-aug.jsonl")
OUT_T1 = os.path.join(ROOT, "data", "agent-traj", "traj-2a-evalshape-t1.jsonl")
OUT_T2 = os.path.join(ROOT, "data", "agent-traj", "traj-2a-evalshape-t2.jsonl")

SYS_BASE = (
    "You are a senior software engineer. When you are given a bug report or a code question, you: "
    "1. Identify the root cause precisely, naming the exact file, function and identifier involved. "
    "2. Give the concrete fix: show the code you would change, in a fenced code block. "
    "3. State how to verify the fix. Answer in the same language as the question. "
    "Do not ask for more information; reason from what is given."
)
SYS_NOTOOL = (
    " TOOLS: none. This is a plain text Q&A — you have no filesystem access. "
    "Never emit <tool_call>, <tool_response>, JSON tool arguments, or ask to read a file. "
    "Answer directly with root cause + fenced code block."
)

DEF = re.compile(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
FILE = re.compile(r"([\w./-]+\.(?:py|js|ts|tsx|go|rs|java|cs|c|cc|cpp|rb|php))")
ERRTYPE = re.compile(
    r"\b(ValueError|TypeError|KeyError|IndexError|AttributeError|RuntimeError|"
    r"ZeroDivisionError|FileNotFoundError|ImportError|AssertionError|NameError|"
    r"RecursionError|OverflowError|StopIteration|TimeoutError)\b")
NARR = re.compile(r"^(##\s*Phase|Let me|\d+\.\s|###\s|\*\*?Phase|Phase\s)")
FENCE = re.compile(r"```")


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "assistant")


def user_of(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "user")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--tier", choices=["t1", "t2"], default="t1")
    ap.add_argument("--n", type=int, default=0, help="上限，0=全部合格行")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    out_path = OUT_T1 if args.tier == "t1" else OUT_T2
    rows = [json.loads(l) for l in io.open(args.src, encoding="utf-8") if l.strip()]
    keep, rej = [], {"tool": 0, "nofence": 0, "nofile": 0, "narr": 0, "nodef": 0}

    for r in rows:
        a = asst(r).strip()
        if not a:
            continue
        if "<tool_call>" in a or "<tool_response>" in a:
            rej["tool"] += 1
            continue
        if a.count("```") < 2:
            rej["nofence"] += 1
            continue
        m_f = FILE.search(a)
        if not m_f:
            rej["nofile"] += 1
            continue
        if NARR.match(a[:120]):
            rej["narr"] += 1
            continue
        m_d = DEF.search(a)
        if args.tier == "t1" and not m_d:
            rej["nodef"] += 1
            continue

        f = m_f.group(1)
        fn = m_d.group(1) if m_d else None
        err = ERRTYPE.search(a)
        err = err.group(1) if err else None
        anchor = re.sub(r"\s+", " ", user_of(r)).strip()[:200]

        if args.tier == "t1":
            head = "`%s` 里的 `%s()` 出问题了：%s" % (f, fn, ("抛出 `%s`" % err) if err else "行为不符合预期")
        else:
            head = "`%s` 里出问题了：%s" % (f, ("抛出 `%s`" % err) if err else "行为不符合预期")

        u = (
            "%s\n\n现象：%s\n\n要求：\n"
            "1. 指名到具体的文件 / 函数 / 标识符\n"
            "2. 直接给出改哪几行，用围栏代码块给出改后代码\n"
            "3. 说明怎么验证\n"
            "4. 不要调用任何工具、不要请求读文件 —— 你没有文件系统访问，按已知信息直接作答"
            % (head, anchor)
        )
        keep.append({
            "messages": [
                {"role": "system", "content": SYS_BASE + SYS_NOTOOL},
                {"role": "user", "content": u},
                {"role": "assistant", "content": a},
            ],
            "meta": {"domain": "swe_evalshape_%s_notool" % args.tier,
                     "src": (r.get("meta") or {}).get("src", ""),
                     "file": f, "func": fn, "err": err},
        })

    random.Random(args.seed).shuffle(keep)
    if args.n:
        keep = keep[:args.n]

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with io.open(out_path, "w", encoding="utf-8", newline="\n") as fo:
        for o in keep:
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")

    tc = sum(1 for o in keep if "<tool_call>" in asst(o))
    code = sum(1 for o in keep if asst(o).count("```") >= 2)
    chars = sum(len(asst(o)) for o in keep)
    print("[tier %s] 源 %d → 产出 %d" % (args.tier, len(rows), len(keep)))
    print("  剔除：含工具标记 %d · 无代码块 %d · 无文件路径 %d · 叙述开头 %d%s"
          % (rej["tool"], rej["nofence"], rej["nofile"], rej["narr"],
             (" · 无 def/class %d" % rej["nodef"]) if args.tier == "t1" else ""))
    print("  自检：tool_call %d（须 0）· 完整代码块 %d/%d · assistant 字符 %d"
          % (tc, code, len(keep), chars))
    print("  → %s" % out_path)
    if tc or code != len(keep):
        sys.exit(1)


if __name__ == "__main__":
    main()
