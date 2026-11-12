#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Z-B v6 训练集构建：v5 mix 去掉负迁移样本 + v6 修正样本

v5 的负迁移来自纪律样本里写死的「一次只给这一个调用，不罗列备选工具」——
它把 L3 多步任务也压成单工具（实测 G11 退步）。
v6 保留 v5 的对比样本（G17 靠它修好），但剔除旧纪律样本，换成允许链式的新版。
"""
import io, json, os, random, collections

HERE = os.path.dirname(os.path.abspath(__file__))
V5_MIX = os.path.join(HERE, "data", "_legacy", "mix-z-re-v5.jsonl")
V6_FIX = os.path.join(HERE, "data", "kitty-reverse", "kitty-v6-fix.jsonl")
OUT = os.path.join(HERE, "data", "_legacy", "mix-z-re-v6.jsonl")

BAN = "一次只给这一个调用，不罗列备选工具"     # v5 纪律原句（负迁移源）
SOFT = ("先给最该做的那一个；需要串联多步时按依赖顺序给出，每一步都写清判据。"
        "禁止的是同一件事罗列备选，不是多步。")


def load(p):
    out = []
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def main():
    random.seed(20251103)
    base = load(V5_MIX)
    fix = load(V6_FIX)

    # 不丢样本，只把负迁移那句话换成允许链式的表述
    # （v5 的 318 条手写对比是 G17 修好的功臣，必须保留）
    rewritten, touched = [], 0
    for r in base:
        m = r["messages"][-1]
        a = m.get("content", "")
        if BAN in a:
            m["content"] = a.replace(BAN, SOFT)
            touched += 1
        rewritten.append(r)

    rows = rewritten + fix
    random.shuffle(rows)
    io.open(OUT, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    print(f"[OUT] {OUT}")
    print(f"  v5 mix {len(base)}（改写纪律句 {touched} 条）")
    print(f"  + v6 修正 {len(fix)}  → {len(rows)} 行")
    # 统计
    kind = collections.Counter()
    for r in rows:
        a = r["messages"][-1].get("content", "")
        if "顺序说明：上一步的回包是下一步的输入" in a:
            kind["多步链"] += 1
        elif "kitty_prot" in a and "易混点" in a:
            kind["对比样本"] += 1
        elif "易混点" in a:
            kind["对比样本"] += 1
        else:
            kind["其他"] += 1
    print("  构成：", dict(kind))


if __name__ == "__main__":
    main()
