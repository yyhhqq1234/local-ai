#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A 方案 Step1：从 v4 的 mix 里筛出 6 组混淆工具的样本，评估 user 侧表述质量

目的：找出「表述质量低」的样本，为 Step2（场景化重写）定坐标。
不改任何数据，只出报告与候选清单。
"""
import io, json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
MIX = os.path.join(HERE, "data", "_legacy", "mix-z-re-v4.jsonl")
OUT_JSON = os.path.join(HERE, "data", "_legacy", "_v8_candidates.json")

# 6 组混淆工具（对应评测里 v4 的 6 条选错 + 参数错）
GROUPS = {
    "init_vs_drv":     ["kitty_init", "kitty_drv"],
    "ida_vs_ghidra":   ["kitty_ida", "kitty_ghidra"],
    "settings_vs_g3":  ["kitty_settings", "reverse_add_target", "reverse_add_obs"],
    "trail_vs_g3":     ["kitty_trail"],
    "ce_vs_prot":      ["kitty_ce", "kitty_prot"],
    "dualview_pchain": ["kitty_dualview", "kitty_pchain"],
}

TOOL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\b")
# 低质表述特征：直接把工具描述当问句 / 只说「用工具跑起来」/ 极短
LOW_QUALITY = [
    re.compile(r"——\s*用工具跑起来"),
    re.compile(r"^用工具完成："),
    re.compile(r"给出调用。$"),
    re.compile(r"按工作台规范做一次"),
    re.compile(r"我要做这件事"),
]


def load(p):
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def getu(r):
    for m in r["messages"]:
        if m["role"] == "user":
            return m["content"]
    return ""


def main():
    rows = load(MIX)
    print(f"[IN] v4 mix {len(rows)} 行")

    # 每条样本的主工具（assistant 里第一个出现的工具名）
    stat = collections.defaultdict(lambda: {"n": 0, "low": 0, "samples": []})
    for r in rows:
        a = r["messages"][-1]["content"]
        u = getu(r)
        tools = TOOL_RE.findall(a)
        if not tools:
            continue
        primary = tools[0]
        for gname, members in GROUPS.items():
            if primary in members:
                d = stat[gname]
                d["n"] += 1
                is_low = any(p.search(u) for p in LOW_QUALITY) or len(u) < 25
                if is_low:
                    d["low"] += 1
                if len(d["samples"]) < 3:
                    d["samples"].append((primary, u[:70]))
                break

    print("\n=== 6 组在 v4 mix 里的分布 ===")
    print(f"  {'组':<20}{'样本数':>7}{'低质表述':>9}{'占比':>8}")
    total = 0
    for g in GROUPS:
        d = stat[g]
        total += d["n"]
        pct = f"{d['low']/d['n']*100:.0f}%" if d["n"] else "—"
        print(f"  {g:<20}{d['n']:>7}{d['low']:>9}{pct:>8}")
    print(f"  {'合计':<20}{total:>7}")

    print("\n=== 各组样例（主工具 | user 前 70 字）===")
    for g in GROUPS:
        d = stat[g]
        if not d["samples"]:
            continue
        print(f"\n[{g}]")
        for t, u in d["samples"]:
            print(f"   {t:<20} {u}")

    # 导出候选（低质表述的样本索引）
    cand = []
    for i, r in enumerate(rows):
        a = r["messages"][-1]["content"]
        u = getu(r)
        tools = TOOL_RE.findall(a)
        if not tools:
            continue
        primary = tools[0]
        in_group = any(primary in m for m in GROUPS.values())
        if not in_group:
            continue
        is_low = any(p.search(u) for p in LOW_QUALITY) or len(u) < 25
        if is_low:
            cand.append({"idx": i, "tool": primary, "user": u[:100],
                         "asst_head": a[:80]})
    io.open(OUT_JSON, "w", encoding="utf-8").write(
        json.dumps(cand, ensure_ascii=False, indent=1))
    print(f"\n[OUT] 低质候选 {len(cand)} 条 → {OUT_JSON}")
    print(f"      这些是 Step2 要重写 user 侧的对象（assistant 不动）")


if __name__ == "__main__":
    main()
