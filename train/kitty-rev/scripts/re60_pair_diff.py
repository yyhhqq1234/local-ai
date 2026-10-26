#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""re60_pair_diff.py —— re60 配对翻正（§16.3 唯一能"判死"的指标）

只读两份 eval_bare 产物，逐题配对算 b / c / 稳过 / 稳失，给 b−c、b+c、精确二项 p、分项表、一行结论。

判据（写死，不许放宽）：
    b−c ≥ 3 且 b+c ≥ 6   -> PASS
    c−b ≥ 3 且 b+c ≥ 6   -> FAIL
    其余                 -> INCONCLUSIVE
    两份 data_sha16 不同 -> NOT_MEASURED（口径污染，不给数）

配对键：题号 i。实测两份产物的 rows[].i 与 re_detail[].i 都是 **1-based**（1..60）；
        本脚本按整数 i 配对，并显式断言两份 i 集合一致（不靠行序，防"顺序变了但长度一样"）。

用法：
    CP=/c/ProgramData/anaconda3/python.exe
    $CP scripts/re60_pair_diff.py --c logs/base-only/re60.json --b logs/v4/eval-B/re60.json
    $CP scripts/re60_pair_diff.py --c C.json --b B.json --json logs/v4/re60-pair.json
    $CP scripts/re60_pair_diff.py --selftest        # 三组假数据：PASS / INCONCLUSIVE / INCONCLUSIVE
"""
import argparse
import json
import os
import sys
from math import comb

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

K_B, K_C, K_FLIP = 3, 6, 6          # b−c≥3 / b+c≥6
PE = "re-pe-identify"               # 饱和&过松：3 条探针正文 0 动作命中，仅单词级命中
CAT_ORDER = ["re-op-syntax", "re-decision-chain", "re-error-recovery", PE]


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def pairs_of(doc, tag):
    """返回 {i:int -> bool pass}；优先 re_detail（判据明细），缺失则退回 rows。"""
    src = doc.get("re_detail") or doc.get("rows") or []
    out, dup = {}, []
    for r in src:
        try:
            i = int(r.get("i"))
        except (TypeError, ValueError):
            continue
        if i in out:
            dup.append(i)
        out[i] = bool(r.get("pass"))
    if dup:
        raise SystemExit(f"[FATAL] {tag} 里 i 重复：{sorted(set(dup))[:8]}")
    if not out:
        raise SystemExit(f"[FATAL] {tag} 里没有 re_detail/rows 的 i+pass")
    return out


def cats_of(doc):
    src = doc.get("re_detail") or doc.get("rows") or []
    return {int(r["i"]): r.get("cat") for r in src if r.get("i") is not None}


def binom_ge(k, n):
    """P(X >= k | n, p=0.5)"""
    if n <= 0:
        return 1.0
    return sum(comb(n, j) for j in range(k, n + 1)) / (2 ** n)


def analyze(cdoc, bdoc):
    sha_c = ((cdoc.get("data") or {}).get("sha16"))
    sha_b = ((bdoc.get("data") or {}).get("sha16"))
    c = pairs_of(cdoc, "C")
    b = pairs_of(bdoc, "B")
    common = sorted(set(c) & set(b))
    cat = cats_of(cdoc)
    cat.update({i: k for i, k in cats_of(bdoc).items() if i not in cat})

    n_b = n_c = st_pass = st_fail = 0
    rows = []
    for i in common:
        pc, pb = c[i], b[i]
        if pb and not pc:
            kind, n_b = "b", n_b + 1
        elif pc and not pb:
            kind, n_c = "c", n_c + 1
        elif pc and pb:
            kind, st_pass = "稳过", st_pass + 1
        else:
            kind, st_fail = "稳失", st_fail + 1
        rows.append({"i": i, "cat": cat.get(i), "C": pc, "B": pb, "kind": kind})

    flips = n_b + n_c
    diff = n_b - n_c
    if sha_c != sha_b:
        verdict = "NOT_MEASURED"
    elif diff >= K_B and flips >= K_FLIP:
        verdict = "PASS"
    elif -diff >= K_B and flips >= K_FLIP:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    p_ge_b = binom_ge(n_b, flips)
    p_two = min(1.0, 2 * min(p_ge_b, binom_ge(n_c, flips)))

    # 分项表
    per = {}
    for r in rows:
        k = r["cat"] or "?"
        d = per.setdefault(k, {"n": 0, "b": 0, "c": 0})
        d["n"] += 1
        if r["kind"] == "b":
            d["b"] += 1
        elif r["kind"] == "c":
            d["c"] += 1

    # 剔除 pe 后的敏感性（阈值解释用）
    np_b = sum(1 for r in rows if r["kind"] == "b" and r["cat"] != PE)
    np_c = sum(1 for r in rows if r["kind"] == "c" and r["cat"] != PE)
    no_pe = {"n": sum(1 for r in rows if r["cat"] != PE), "b": np_b, "c": np_c,
             "diff": np_b - np_c, "flips": np_b + np_c,
             "verdict": ("PASS" if np_b - np_c >= K_B and np_b + np_c >= K_FLIP else
                         "FAIL" if np_c - np_b >= K_B and np_b + np_c >= K_FLIP else
                         "INCONCLUSIVE")}

    return {"data_sha16": {"C": sha_c, "B": sha_b}, "common": len(common),
            "only_C": sorted(set(c) - set(b)), "only_B": sorted(set(b) - set(c)),
            "b": n_b, "c": n_c, "stable_pass": st_pass, "stable_fail": st_fail,
            "b_minus_c": diff, "b_plus_c": flips, "p_ge_b": p_ge_b, "p_two": p_two,
            "verdict": verdict, "per_cat": per, "excl_pe": no_pe, "rows": rows}


def render(res, cpath, bpath, verbose=False):
    print("=" * 78)
    print(f"[in] C = {cpath}")
    print(f"[in] B = {bpath}")
    print(f"[sha] C={res['data_sha16']['C']}  B={res['data_sha16']['B']}"
          f"  {'✓ 同 data' if res['data_sha16']['C'] == res['data_sha16']['B'] else '✗ 不同 data → NOT_MEASURED'}")
    print(f"[pair] 共同题数={res['common']}  仅C有={res['only_C']}  仅B有={res['only_B']}")
    print("-" * 78)
    print(f"[count] b(B过C不过)={res['b']}  c(C过B不过)={res['c']}  "
          f"稳过={res['stable_pass']}  稳失={res['stable_fail']}  ⇒ b−c={res['b_minus_c']}  b+c={res['b_plus_c']}")
    print(f"[binom] p(P(X≥b)|p=.5, n=b+c)={res['p_ge_b']:.4f}   双侧≈{res['p_two']:.4f}")
    print("-" * 78)
    print(f"{'cat':<20s} {'n':>3s} {'b':>3s} {'c':>3s} {'净':>4s}   备注")
    for k in CAT_ORDER + [x for x in res["per_cat"] if x not in CAT_ORDER]:
        if k not in res["per_cat"]:
            continue
        d = res["per_cat"][k]
        note = "饱和&过松，不计入可提升空间" if k == PE else ""
        print(f"{k:<20s} {d['n']:>3d} {d['b']:>3d} {d['c']:>3d} {d['b'] - d['c']:>+4d}   {note}")
    e = res["excl_pe"]
    print(f"{'[剔除 pe 后]':<20s} {e['n']:>3d} {e['b']:>3d} {e['c']:>3d} {e['diff']:>+4d}   "
          f"b+c={e['flips']} → {e['verdict']}")
    print("-" * 78)
    if verbose:
        for r in res["rows"]:
            if r["kind"] in ("b", "c"):
                print(f"  [flip] i={r['i']:<3d} {r['cat']:<20s} C={int(r['C'])} B={int(r['B'])} -> {r['kind']}")
    print(f"[RE60-PAIR] b={res['b']} c={res['c']} b-c={res['b_minus_c']} b+c={res['b_plus_c']} "
          f"p={res['p_ge_b']:.4f} → {res['verdict']} | 有效分母={res['common']}"
          f"（其中 pe 15 项 saturated&loose，不计入可提升空间）")
    return res["verdict"]


# ------------------------------------------------------------------ selftest
def _fake(name, pattern, cat=None):
    """pattern: {'pass': [...]} 60 题；cat 按 15/15/15/15 铺。"""
    cats = (["re-op-syntax"] * 15 + ["re-decision-chain"] * 15 +
            ["re-error-recovery"] * 15 + [PE] * 15)
    rows = [{"i": k + 1, "cat": cats[k], "pass": bool(v)} for k, v in enumerate(pattern)]
    return {"suite": "re60", "data": {"sha16": "cee81a964255e09c", "rows": 60},
            "re_detail": [{"i": r["i"], "pass": r["pass"], "cat": r["cat"]} for r in rows],
            "rows": rows, "tag": name}


def run_selftest():
    print("== re60_pair_diff --selftest ==")
    base = [True] * 24 + [False] * 36                  # 24/60，与 C 同形
    # ① 翻正 5 / 翻负 1：前 5 个 False→True，一个 True→False（净 +4，b+c=6）→ PASS
    p1 = list(base)
    for k in (24, 25, 26, 27, 28):
        p1[k] = True
    p1[0] = False
    # ② 全稳过：两边完全一样 → 0 翻转 → INCONCLUSIVE
    p2 = list(base)
    # ③ 只有 1 个翻转 → b+c=1 < 6 → INCONCLUSIVE
    p3 = list(base)
    p3[24] = True
    cases = [("翻正5/翻负1", p1, "PASS"), ("全稳过", p2, "INCONCLUSIVE"), ("单翻转", p3, "INCONCLUSIVE")]
    ok = True
    for name, pat, want in cases:
        c = _fake("C", base)
        b = _fake("B", pat)
        res = analyze(c, b)
        got = render(res, f"<selftest:{name}> C", f"<selftest:{name}> B")
        flag = "PASS" if got == want else "FAIL"
        ok = ok and got == want
        print(f"[selftest] {name}: 期望 {want} / 实得 {got} -> {flag}\n")
    print(f"SELFTEST: {'3/3 ALL PASS' if ok else 'FAILED'}")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description="re60 配对翻正（只读两份 eval_bare 产物）")
    ap.add_argument("--c", default="", help="C 组 re60.json")
    ap.add_argument("--b", default="", help="B 组 re60.json")
    ap.add_argument("--json", default="", help="报告落盘路径（可选）")
    ap.add_argument("--verbose", action="store_true", help="逐条打印翻转题面号")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return run_selftest()
    if not a.c or not a.b:
        print(__doc__)
        return 2
    for p in (a.c, a.b):
        if not os.path.isfile(p):
            print(f"[FATAL] 文件不存在：{p}", file=sys.stderr)
            return 2
    res = analyze(load(a.c), load(a.b))
    v = render(res, a.c, a.b, verbose=a.verbose)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        back = json.load(open(a.json, encoding="utf-8"))
        assert back["verdict"] == res["verdict"]
        print(f"[ok] 报告 → {a.json}（回读一致）")
    return {"PASS": 0, "FAIL": 1}.get(v, 3)     # INCONCLUSIVE → 3, NOT_MEASURED → 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
