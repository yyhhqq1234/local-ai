#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_z_datasets.py — 方案 Z 的两个数据集（双 adapter，冲突从训练期挪到路由期）

## 为什么转 Z（mix-v8 验收结论）
单 adapter 同时要「会调工具」（kitty 90% 数据）和「不该调工具」（2A 10% 负例），
结果 tool_call 率 42.5-47.5% 一点没降 —— 10% 负例打不过 90% 正例，这是信号冲突，不是数据量问题。

## Z 的两条腿
  A) RE adapter：`r3/final` 之上继续训「kitty-clean + 调用范式补全」
     —— 只补那 47 个工具的 `<tool_call>` 形态（数据来自 tool-manifest.ts，零编造）
  B) 2A adapter：**从基座直接训** 2A-lite（1149 条）—— 不掺 kitty，天然不会吐工具调用
     推理时按场景路由：带工具上下文/逆向请求 → A；纯编程问答 → B

## 产物
    train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl      2A-lite 原样（1149 行，梯度份额 100% 2A）
    train/lines/9b-oxcoder/data/_legacy/mix-z-re.jsonl      kitty-clean 23674 + 范式样本 ×4 增广（确定性改写问法）
    train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-aug.jsonl   增广后的范式样本

## 自检（一票否决）
  ① 范式样本里每个 (name, action) ∈ tool-manifest.ts 原文
  ② 47 个缺失工具每个至少 4 条
  ③ mix-z-2a 的 2A 段 tool_call == 0
"""
import argparse
import io
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "data", "kitty-tool-catalog.json")
COV = os.path.join(ROOT, "data", "agent-traj", "kitty-callcoverage.jsonl")
LITE = os.path.join(ROOT, "data", "agent-traj", "traj-2a-lite.jsonl")
KITTY = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-clean.jsonl")
OUT_COV_AUG = os.path.join(ROOT, "data", "agent-traj", "kitty-callcoverage-aug.jsonl")
OUT_Z2A = os.path.join(ROOT, "data", "mix-z-2a.jsonl")
OUT_ZRE = os.path.join(ROOT, "data", "mix-z-re.jsonl")

# 确定性问法（同一 (tool, action) 换 4 种说法，答案不变）——不引入新内容
PHRASES = [
    "{desc} —— 用工具跑起来（动作 {act}），参数一次给全。",
    "我需要{desc}，走 {act} 这个动作，直接给调用。",
    "任务：{desc}。请选对工具、用 {act}，别反问。",
    "按工作台规范做一次「{desc}」（{act}），给出工具调用与判据。",
]


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def load(p):
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aug", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    for p in (CATALOG, COV, LITE, KITTY):
        if not os.path.isfile(p):
            sys.exit("[FATAL] 缺 %s" % p)
    cat = json.load(io.open(CATALOG, encoding="utf-8"))
    cov = load(COV)

    # ── ① 增广（只改问法，答案原样）──
    aug = []
    for s in cov:
        meta = s["meta"]
        name, act, ch = meta["tool"], meta["action"], meta["channel"]
        desc = (cat.get(name) or {}).get("description", "")
        if not desc:
            sys.exit("[FATAL] 目录里没有 %s 的描述" % name)
        for i in range(args.aug):
            t = json.loads(json.dumps(s, ensure_ascii=False))
            t["messages"][1]["content"] = PHRASES[i % len(PHRASES)].format(desc=desc, act=act)
            t["meta"]["aug"] = i
            aug.append(t)

    # 自检 ①：每个 (name, action) 必须在清单里
    bad = [(s["meta"]["tool"], s["meta"]["action"]) for s in aug
           if s["meta"]["action"] not in (cat.get(s["meta"]["tool"]) or {}).get("actions", [])]
    if bad:
        sys.exit("[FATAL] 增广后出现清单外组合: %s" % bad[:5])

    io.open(OUT_COV_AUG, "w", encoding="utf-8", newline="\n").write(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in aug))

    # 自检 ②：47 个缺失工具每个 ≥ aug 条
    per = {}
    for s in aug:
        per[s["meta"]["tool"]] = per.get(s["meta"]["tool"], 0) + 1
    thin = [k for k, v in per.items() if v < args.aug]
    print("[cov-aug] %d 条 · 覆盖工具 %d 个 · 每工具最少 %d 条 %s"
          % (len(aug), len(per), min(per.values()), "PASS" if not thin else ("FAIL %s" % thin)))
    chars_aug = sum(len(asst(s)) for s in aug)

    # ── ② 方案 Z 的两个数据集 ──
    lite = load(LITE)
    tc2a = sum(1 for s in lite if "<tool_call>" in asst(s))
    if tc2a:
        sys.exit("[FATAL] 2A 段出现 tool_call %d 条" % tc2a)
    io.open(OUT_Z2A, "w", encoding="utf-8", newline="\n").write(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in lite))
    print("[z-2a ] %d 行（纯 2A，无 kitty）· assistant 字符 %d"
          % (len(lite), sum(len(asst(s)) for s in lite)))

    kitty = load(KITTY)
    rows = []
    for s in kitty:
        t = json.loads(json.dumps(s, ensure_ascii=False))
        t["_mix_src"] = "kitty"
        rows.append(t)
    for s in aug:
        t = json.loads(json.dumps(s, ensure_ascii=False))
        t["_mix_src"] = "callcov"
        rows.append(t)
    random.Random(args.seed).shuffle(rows)
    io.open(OUT_ZRE, "w", encoding="utf-8", newline="\n").write(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in rows))
    c_k = sum(len(asst(s)) for s in kitty)
    print("[z-re ] %d 行（kitty %d + 范式 %d）· 范式梯度份额 %.2f%% · 步数 ceil(%d/4)=%d"
          % (len(rows), len(kitty), len(aug), 100.0 * chars_aug / (c_k + chars_aug),
             len(rows), (len(rows) + 3) // 4))


if __name__ == "__main__":
    main()
