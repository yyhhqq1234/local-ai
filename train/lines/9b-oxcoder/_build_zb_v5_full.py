#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Z-B v5 数据强化：把工具判别能力全部放进训练，不依赖 system 索引 / 外部路由

背景：v5 首版只有 318 条对比样本（6 组手写混淆对 + 裸OP + 纪律），占 8%。
     但 40 条评测里错的不止这 6 组 —— 58 个工具之间还有大量名字相近 / 功能重叠的对。
     本脚本把「判别能力」系统性地灌进训练集：

  ① 全工具正例（58 × 4 句式 = 232 条）
     每个工具至少出现一次正确调用，覆盖 catalog 全部 action 组
  ② 自动易混对辨析（名字相似 + 描述重叠，取 top-N 对 × 4 句式）
     不只手写的 6 组 —— 用算法找出所有近距离工具对
  ③ 保留 v5 首版的 318 条（含裸 OP 纠正 + 单一工具纪律）

输出：data/kitty-reverse/kitty-v5-strong.jsonl
"""
import json, os, re, io, itertools, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CAT_PATH = os.path.join(HERE, "data", "kitty-tool-catalog.json")
V5 = os.path.join(HERE, "data", "kitty-reverse", "kitty-v5-contrast.jsonl")
OUT = os.path.join(HERE, "data", "kitty-reverse", "kitty-v5-strong.jsonl")

CAT = json.load(io.open(CAT_PATH, encoding="utf-8"))
NAMES = sorted(CAT.keys())


def desc(t):
    return " ".join(str(CAT[t].get("description") or "").split())


def acts(t):
    return CAT[t].get("actions") or []


def main_act(t):
    a = acts(t)
    pref = ["status", "scan", "get", "list", "analyze", "query", "op", "ensure"]
    for p in pref:
        if p in a:
            return p
    return a[0] if a else "status"


# ── 名字相似度（编辑距离）+ 描述重叠（2-gram Jaccard）──────────
def ed(a, b):
    if abs(len(a) - len(b)) > 6:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def bigrams(s):
    s = re.sub(r"\s+", "", s)
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))


def jac(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def confusion_pairs(top_n=26, min_name_ed=4, min_desc_jac=0.12):
    """按**功能域**挑易混对（不是名字相似 —— 名字相似但语义无关的对没有训练价值）

    评测实测的错点全部落在同域不同工具上：
      kitty_init ↔ kitty_drv（通道）· kitty_ida ↔ kitty_ghidra（静态）
      kitty_ce ↔ kitty_prot（内存）· kitty_dualview 被拆成 ce+km+prot（内存）
    所以同域两两才是真正需要的负例来源。
    """
    DOMAINS = {
        "channel":  ["kitty_init", "kitty_drv", "kitty_drvio", "kitty_status",
                     "kitty_variants", "kitty_selftest", "kitty_engines"],
        "memory":   ["kitty_ce", "kitty_km", "kitty_prot", "kitty_wpb",
                     "kitty_pchain", "kitty_dualview", "kitty_acescan"],
        "static":   ["kitty_ida", "kitty_ghidra", "kitty_rea", "kitty_sym",
                     "kitty_asm", "kitty_die"],
        "debug":    ["kitty_dbg", "kitty_x64dbg"],
        "session":  ["kitty_settings", "kitty_trail", "kitty_loop",
                     "kitty_loop_status", "kitty_ops"],
        "engine":   ["kitty_dnspy", "kitty_il2cppdumper", "kitty_cpp2il",
                     "kitty_uedump", "kitty_ue4ss", "kitty_uexplorer",
                     "kitty_assetrip", "kitty_bepinex", "kitty_gdre", "kitty_fmodel"],
        "mobile":   ["kitty_apktool", "kitty_jadx", "kitty_apkscan",
                     "kitty_frida", "kitty_unpack", "kitty_rea_android",
                     "kitty_rea_method"],
        "net":      ["kitty_net", "kitty_proto"],
        "inject":   ["kitty_inject", "kitty_dump"],
    }
    picked = []
    for dom, members in DOMAINS.items():
        members = [m for m in members if m in CAT]
        for a, b in itertools.combinations(members, 2):
            d = ed(a, b)
            j = round(jac(desc(a), desc(b)), 3)
            # 同域内一律算候选；分数用于排序（域内越"像"越优先）
            picked.append((round(1.0 / (1 + d) * 0.6 + j * 0.4, 3), d, j, a, b))
    picked.sort(reverse=True)
    return picked[:top_n]


PHRASES = [
    "{d} —— 用工具跑起来，给一条调用。",
    "我要{d}。选对工具，参数一次给全。",
    "任务：{d}。别反问，直接给调用和判据。",
    "按工作台规范做一次「{d}」，给出工具调用。",
]

CRIT = ("判据：回包首行看 OK/ERR；ERR 先按错误码修参数，不要原地重试。"
        "一次只给这一个调用，不罗列备选工具。")


def asst_positive(t):
    a = main_act(t)
    return (f"{t} action={a}\n\n"
            f"选它的理由：{desc(t)}\n"
            f"参数要点：先把目标定死（path / pid / addr 按任务给全），只读类先 status 探一次。\n"
            f"{CRIT}")


def asst_contrast(a, b):
    aa = main_act(a)
    return (f"{a} action={aa}\n\n"
            f"选它的理由：{desc(a)}\n"
            f"易混点：{b} —— 它做的是「{desc(b)}」。本任务要的是「{desc(a)}」，所以选 {a} 不选 {b}。\n"
            f"两者 action 面也不同：{a} 有 {','.join(acts(a)[:5])}；"
            f"{b} 有 {','.join(acts(b)[:5])}。\n"
            f"{CRIT}")


def main():
    rows = []

    # ① 全工具正例
    for t in NAMES:
        for ph in PHRASES:
            rows.append({"messages": [
                {"role": "user", "content": ph.format(d=desc(t))},
                {"role": "assistant", "content": asst_positive(t)}],
                "meta": {"src": "v5strong-positive", "tool": t}})
    n1 = len(rows)

    # ② 自动易混对辨析（双向各一条，让模型两侧都见过）
    pairs = confusion_pairs()
    for s, d, j, a, b in pairs:
        for ph in PHRASES[:2]:
            rows.append({"messages": [
                {"role": "user", "content": ph.format(d=desc(a))},
                {"role": "assistant", "content": asst_contrast(a, b)}],
                "meta": {"src": "v5strong-contrast", "a": a, "b": b,
                         "name_ed": d, "desc_jac": j}})
            rows.append({"messages": [
                {"role": "user", "content": ph.format(d=desc(b))},
                {"role": "assistant", "content": asst_contrast(b, a)}],
                "meta": {"src": "v5strong-contrast", "a": b, "b": a,
                         "name_ed": d, "desc_jac": j}})
    n2 = len(rows) - n1

    # ③ 保留 v5 首版 318 条
    old = []
    if os.path.exists(V5):
        for line in io.open(V5, encoding="utf-8"):
            if line.strip():
                old.append(json.loads(line))
    rows.extend(old)              # 先放 1 份参与去重

    # 去重
    seen, out = set(), []
    for r in rows:
        k = r["messages"][0]["content"] + "\x00" + r["messages"][1]["content"]
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out.extend(old * 5)          # 去重后补 5 份：手写错点组共 6 份

    with io.open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[OUT] {OUT}")
    print(f"  全工具正例 {n1} · 自动易混对 {n2} · v5首版 {len(old)} → 去重 {len(out)}")
    print(f"  覆盖工具数：{len({r['meta'].get('tool') for r in out if r['meta'].get('tool')})} / {len(NAMES)}")
    print("\n=== 自动挑出的易混对（前 26）===")
    for s, d, j, a, b in pairs:
        print(f"  {a:<18} ↔ {b:<18}  名字ed={d:<2} 描述jac={j}")
    print("\n=== 样本抽检（一对）===")
    if pairs:
        _, _, _, a, b = pairs[0]
        print("U:", PHRASES[0].format(d=desc(a)))
        print("A:", asst_contrast(a, b)[:400])


if __name__ == "__main__":
    main()
