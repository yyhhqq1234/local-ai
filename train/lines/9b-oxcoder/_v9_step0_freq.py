#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B1/B2 混合方案 Step0：探查各工具的真实使用频率，定人工重写 / 删除的分界

三个维度：
  A 训练集频率   v4 mix 7608 条里各工具作为主工具的样本数
  B 评测集频率   40 条 RE 用例里 expect 出现的次数（考核权重）
  C 真实轨迹频率 kitty-v3-clean 23674 条里各工具被调用的次数（真实使用强度）

综合分 = 归一化后的加权和（评测权重最高，因为它直接决定验收）
"""
import io, json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
MIX = os.path.join(HERE, "data", "_legacy", "mix-z-re-v4.jsonl")
CLEAN = os.path.join(HERE, "data", "kitty-reverse", "train-kitty-v3-clean.jsonl")
OUT = os.path.join(HERE, "data", "_legacy", "_freq_report.json")

TOOL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\b")
CALL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\s+action=([\w\-]+)")
TC_JSON = re.compile(r'<tool_call>\s*\{[^}]*"name"\s*:\s*"([a-z_]+)"')

# 6 组混淆工具（无调用样本要处理的边界）
GROUPS = {
    "init_vs_drv":     ["kitty_init", "kitty_drv"],
    "ida_vs_ghidra":   ["kitty_ida", "kitty_ghidra"],
    "settings_vs_g3":  ["kitty_settings", "reverse_add_target", "reverse_add_obs"],
    "trail_vs_g3":     ["kitty_trail"],
    "ce_vs_prot":      ["kitty_ce", "kitty_prot"],
    "dualview_pchain": ["kitty_dualview", "kitty_pchain"],
}
GTOOLS = set(t for v in GROUPS.values() for t in v)


def getu(r):
    for m in r["messages"]:
        if m["role"] == "user":
            return m["content"]
    return ""


def geta(r):
    return r["messages"][-1]["content"]


def has_call(a):
    return bool(CALL_RE.search(a) or TC_JSON.search(a))


def main():
    # ── A 训练集频率 ──
    mix = [json.loads(l) for l in io.open(MIX, encoding="utf-8") if l.strip()]
    A = collections.Counter()
    A_nocall = collections.Counter()
    for r in mix:
        a = geta(r)
        t = TOOL_RE.findall(a)
        if not t:
            continue
        A[t[0]] += 1
        if not has_call(a):
            A_nocall[t[0]] += 1

    # ── B 评测集频率 ──
    import sys
    sys.path.insert(0, os.path.join(HERE, "..", "_shared", "scripts"))
    from eval_cases_re import CASES
    B = collections.Counter()
    for c in CASES:
        for t in (c.get("expect") or []):
            B[t] += 1

    # ── C 真实轨迹频率 ──
    C = collections.Counter()
    if os.path.exists(CLEAN):
        for line in io.open(CLEAN, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            a = geta(r)
            for t in set(TOOL_RE.findall(a)):
                C[t] += 1

    # ── 只关心 6 组内的工具 ──
    print("=" * 96)
    print("6 组混淆工具的三维频率（A=训练集条数 · B=评测expect次数 · C=真实轨迹调用次数）")
    print("=" * 96)
    print(f"  {'工具':<20}{'A训练':>7}{'其中无调用':>10}{'无调用%':>8}{'B评测':>7}{'C轨迹':>8}")
    rows = []
    for t in sorted(GTOOLS):
        a, an, b, c = A.get(t, 0), A_nocall.get(t, 0), B.get(t, 0), C.get(t, 0)
        pct = f"{an/a*100:.0f}%" if a else "—"
        print(f"  {t:<20}{a:>7}{an:>10}{pct:>8}{b:>7}{c:>8}")
        rows.append(dict(tool=t, A=a, A_nocall=an, B=b, C=c))

    # ── 综合评分 ──
    def norm(vals):
        mx = max(vals) or 1
        return [v / mx for v in vals]
    nA = norm([r["A"] for r in rows])
    nB = norm([r["B"] for r in rows])
    nC = norm([r["C"] for r in rows])
    for i, r in enumerate(rows):
        # 评测权重 0.5（直接决定验收）、训练 0.2、真实使用 0.3
        r["score"] = round(nB[i] * 0.5 + nA[i] * 0.2 + nC[i] * 0.3, 3)

    rows.sort(key=lambda x: -x["score"])
    print("\n" + "=" * 96)
    print("综合评分（评测 0.5 + 训练 0.2 + 真实 0.3）→ 排序")
    print("=" * 96)
    print(f"  {'工具':<20}{'score':>7}{'B评测':>7}{'C轨迹':>8}{'无调用条数':>10}  建议")
    hi, lo = [], []
    for r in rows:
        if r["A_nocall"] == 0:
            verdict = "无需处理"
        elif r["score"] >= 0.45:
            verdict = "**B2 人工重写**"
            hi.append(r)
        else:
            verdict = "B1 删除"
            lo.append(r)
        print(f"  {r['tool']:<20}{r['score']:>7}{r['B']:>7}{r['C']:>8}"
              f"{r['A_nocall']:>10}  {verdict}")

    print("\n" + "=" * 96)
    print("分界结论")
    print("=" * 96)
    hs = sum(r["A_nocall"] for r in hi)
    ls = sum(r["A_nocall"] for r in lo)
    print(f"  B2 人工重写：{len(hi)} 个工具，共 {hs} 条无调用样本")
    for r in hi:
        print(f"     {r['tool']:<20}{r['A_nocall']:>5} 条  (评测出现 {r['B']} 次 · 轨迹 {r['C']} 次)")
    print(f"\n  B1 删除：{len(lo)} 个工具，共 {ls} 条无调用样本")
    for r in lo:
        print(f"     {r['tool']:<20}{r['A_nocall']:>5} 条  (评测出现 {r['B']} 次 · 轨迹 {r['C']} 次)")
    print(f"\n  合计处理 {hs + ls} 条 · 数据 7608 → {7608 - ls}（删 {ls}、重写 {hs} 保留行数）")

    io.open(OUT, "w", encoding="utf-8").write(json.dumps(
        {"rows": rows, "b2_tools": [r["tool"] for r in hi],
         "b1_tools": [r["tool"] for r in lo],
         "b2_rows": hs, "b1_rows": ls}, ensure_ascii=False, indent=1))
    print(f"\n[OUT] {OUT}")


if __name__ == "__main__":
    main()
