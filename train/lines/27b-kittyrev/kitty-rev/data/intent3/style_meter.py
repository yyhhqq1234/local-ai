#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""style_meter.py — 语体量化（不是拒答机制，只量“是否直接进正题”）

对任意 jsonl 的回答算三个指标：
  first_sentence_action  首句是否以动词 / 工具调用 / OP 开头（不许“这个/首先/需要”起手）
  preamble_30            前 30 字是否含铺垫词（在授权/合法/请注意/首先需要/建议…）
  judge_density          (工具调用行数 + 判据序号数) / 百字

输出逐条 + 汇总；--strict 时按阈值给退出码（默认只报告，不判死）。

用法：
  python style_meter.py --input re-sft.jsonl --details
  python style_meter.py --input re-sft.messages.jsonl --json logs/style.json
  python style_meter.py --input A.jsonl --baseline B.jsonl   # 两组对比
"""
import argparse
import json
import re
import statistics
import sys

TOOL_LINE_RE = re.compile(r"^\s*(kitty_[a-z0-9_]+|reverse_[a-z0-9_]+|cdb\b|unsquashfs\b)")
OP_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*\|")          # PING / R|0x… / S_NEW|…
JUDGE_RE = re.compile(r"判据[一二三四五六七八九十1-9]|判据\s*[：:]")

# 动作动词（首字/首词即判为“直接进正题”）
ACTION_VERBS = (
    "先", "取", "跑", "查", "看", "读", "算", "用", "装", "下", "抓", "打开", "执行",
    "启动", "定位", "确认", "对比", "统计", "解析", "提取", "列", "找", "断", "改",
    "dump", "run", "open", "scan", "trace", "decompile", "attach", "hook", "sweep",
)
# 铺垫/非动作起手
BAD_STARTERS = (
    "这个", "首先", "需要", "如果", "在", "为了", "建议", "可以", "我们", "你", "它",
    "那", "所谓", "一般", "通常", "理论", "值得", "应该", "请", "关于", "对于",
    "作为一个", "作为", "鉴于", "考虑到", "值得注意的是", "毫无疑问",
)
PREAMBLE_WORDS = (
    "在授权", "授权前", "合法", "请注意", "首先需要", "建议", "需要说明", "如果你拥有",
    "仅供", "前提是", "出于安全", "请确保", "免责", "在开始之前", "务必",
)


def answer_of(row):
    if isinstance(row.get("response"), str):
        return row["response"]
    msgs = row.get("messages")
    if isinstance(msgs, list):
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
                return m["content"]
    for k in ("text", "content", "answer"):
        if isinstance(row.get(k), str):
            return row[k]
    return None


def first_sentence(text):
    s = text.lstrip()
    if s.startswith("```"):
        lines = s.splitlines()[1:]
        s = "\n".join(lines).lstrip()
    # 取到第一个句末标点或换行
    m = re.search(r"[。！？!?\n]", s)
    return (s[:m.start()] if m else s).strip()


def is_action(first):
    if not first:
        return False
    if TOOL_LINE_RE.match(first) or OP_LINE_RE.match(first):
        return True
    for bad in BAD_STARTERS:
        if first.startswith(bad):
            return False
    for v in ACTION_VERBS:
        if first.startswith(v):
            return True
    return False


def has_preamble(text):
    head = text.lstrip()[:30]
    return any(w in head for w in PREAMBLE_WORDS)


def judge_density(text):
    if not text:
        return 0.0
    tool_lines = sum(1 for ln in text.splitlines() if TOOL_LINE_RE.match(ln))
    judge_marks = len(JUDGE_RE.findall(text))
    return round((tool_lines + judge_marks) * 100.0 / max(len(text), 1), 3)


def meter(rows):
    items = []
    for r in rows:
        a = answer_of(r)
        if a is None:
            items.append({"id": r.get("id"), "error": "no-answer"})
            continue
        first = first_sentence(a)
        items.append({
            "id": r.get("id"),
            "chars": len(a),
            "first_sentence_action": bool(is_action(first)),
            "preamble_30": bool(has_preamble(a)),
            "judge_density": judge_density(a),
            "first": first[:40],
        })
    good = [i for i in items if "error" not in i]
    n = len(good)
    return {
        "n": n,
        "first_sentence_action_rate": round(sum(i["first_sentence_action"] for i in good) / n, 4) if n else None,
        "preamble_30_rate": round(sum(i["preamble_30"] for i in good) / n, 4) if n else None,
        "judge_density_mean": round(statistics.mean(i["judge_density"] for i in good), 3) if n else None,
        "judge_density_median": round(statistics.median(i["judge_density"] for i in good), 3) if n else None,
        "judge_density_min": min((i["judge_density"] for i in good), default=None),
        "judge_density_max": max((i["judge_density"] for i in good), default=None),
        "items": items,
    }


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser(description="语体量化：首句动作 / 30 字铺垫 / 判据密度")
    ap.add_argument("--input", required=True)
    ap.add_argument("--baseline", help="对照 jsonl，输出两组差值")
    ap.add_argument("--json", help="报告输出路径")
    ap.add_argument("--details", action="store_true", help="逐条打印")
    ap.add_argument("--min-action-rate", type=float, default=0.9)
    ap.add_argument("--max-preamble-rate", type=float, default=0.05)
    ap.add_argument("--strict", action="store_true", help="按阈值判退出码")
    args = ap.parse_args()

    rep = meter(load(args.input))
    rep["input"] = args.input
    if args.baseline:
        base = meter(load(args.baseline))
        rep["baseline"] = {k: base[k] for k in
                           ("n", "first_sentence_action_rate", "preamble_30_rate", "judge_density_mean")}
        rep["delta"] = {
            "first_sentence_action_rate": round(rep["first_sentence_action_rate"] - base["first_sentence_action_rate"], 4)
            if rep["first_sentence_action_rate"] is not None and base["first_sentence_action_rate"] is not None else None,
            "preamble_30_rate": round(rep["preamble_30_rate"] - base["preamble_30_rate"], 4)
            if rep["preamble_30_rate"] is not None and base["preamble_30_rate"] is not None else None,
            "judge_density_mean": round(rep["judge_density_mean"] - base["judge_density_mean"], 3)
            if rep["judge_density_mean"] is not None and base["judge_density_mean"] is not None else None,
        }

    if args.details:
        for i in rep["items"]:
            if "error" in i:
                print(f"{i['id']}: ERROR {i['error']}")
            else:
                flag = "A" if i["first_sentence_action"] else "x"
                pre = "P" if i["preamble_30"] else "-"
                print(f"{i['id']:<8} {flag}{pre} dens={i['judge_density']:<5} chars={i['chars']:<4} | {i['first']}")

    print("\n===== STYLE SUMMARY =====")
    print(f"n={rep['n']}")
    print(f"first_sentence_action_rate = {rep['first_sentence_action_rate']}")
    print(f"preamble_30_rate           = {rep['preamble_30_rate']}")
    print(f"judge_density mean/median/min/max = {rep['judge_density_mean']}/"
          f"{rep['judge_density_median']}/{rep['judge_density_min']}/{rep['judge_density_max']}")
    if "delta" in rep:
        print(f"delta vs baseline: {rep['delta']}")

    if args.json:
        import os
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)

    if args.strict:
        ok = (rep["first_sentence_action_rate"] is not None
              and rep["first_sentence_action_rate"] >= args.min_action_rate
              and rep["preamble_30_rate"] is not None
              and rep["preamble_30_rate"] <= args.max_preamble_rate)
        print(f"[strict] {'PASS' if ok else 'FAIL'} "
              f"(action>={args.min_action_rate}, preamble<={args.max_preamble_rate})")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
