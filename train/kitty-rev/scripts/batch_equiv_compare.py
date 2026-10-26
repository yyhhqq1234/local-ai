#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""batch_equiv_compare.py —— batch=1 vs batch=4 等价性取证（判据写死，不许放宽）

用途
  runB_all.sh --batch-check 用它出结论。今晚省 1.5 小时的唯一杠杆：
  只有证明 batch=4 与 batch=1 逐题等价，其余三套才允许用 batch=4 提速。

三条判据（lead 2026-10-22 写死）
  G1 pass 向量完全相同：40 题逐题 pass 布尔逐条比对（按 i 对齐，题目集合必须一致）
  G2 mean_f1 **完全相同**（不是"接近"；不等就打印差值并 FAIL）
     —— 同时比对 mean_ref_recall（存在时同标准）
  G3 逐题 f1 向量完全相同
     ⚠ 事实：现有 bench40 产物 re_detail 只有 {i, pass, cat, contaminated}，**没有逐题 f1**。
       本项因此做自动探测：两侧都带逐题 f1（f1 / score / ref_recall / metrics.f1）才比对；
       不带 → 记 UNAVAILABLE（不是 PASS，也不是 FAIL），并用下面三条同源硬代理顶上：
         G3a 逐题 head 文本完全一致（不同 = 生成已经分叉，f1 必然不同）
         G3b 逐题 chars 完全一致
         G3c 计数 n_ok / n_err / n_empty 完全一致
       要真正比对 f1 向量，得先让评测脚本落逐题 f1（改 eval_* 需 lead 批准）。
  G4 顶层指标集一致：suite / judge / data.sha16 / protocol.max_tokens 相同
     （同参才谈得上等价；参数不同就不是 batch 的锅，是尺子换了）

关于"浮点必须完全相等"是否误伤（结论：不会，见 --why）
  f1 是由文本算出来的：批处理只影响前向的归约顺序，若生成 token 完全相同，
  逐题 f1 与均值就是同一串浮点运算 → 按位相同；若浮点不同，说明生成文本已不同，
  那时 f1 不同是**真实分歧**，必须 FAIL 而不是用容差糊过去。
  因此本脚本用 ==  比较，并把差值打出来供人判断；容差只用于显示，不参与判定。

退出码：0 = PASS（可用 batch=4）/ 1 = FAIL（全部 batch=1）/ 2 = 输入缺失

用法
  C:\\ProgramData\\anaconda3\\python.exe batch_equiv_compare.py \
      logs\\v4\\eval-B\\batchcheck\\bench40-b1.json logs\\v4\\eval-B\\batchcheck\\bench40-b4.json \
      [--out logs\\v4\\eval-B\\batchcheck\\verdict.json] [--why]
"""

import json
import os
import sys

PASS, FAIL, NA = "PASS", "FAIL", "UNAVAILABLE"

ITEM_KEYS = ("re_detail", "rows", "results")
F1_KEYS = ("f1", "score", "ref_recall", "recall")


def load(p):
    with open(p, "rb") as f:
        return json.loads(f.read().decode("utf-8", "replace"))


def norm_items(doc):
    """→ {i: item}，按题号对齐。re_detail 优先（携带 pass），否则 rows。"""
    for k in ITEM_KEYS:
        v = doc.get(k)
        if isinstance(v, list) and v:
            out = {}
            for j, it in enumerate(v):
                if not isinstance(it, dict):
                    continue
                key = it.get("i", it.get("idx", j))
                out[int(key) if isinstance(key, (int, float)) else str(key)] = it
            if out:
                return k, out
    return None, {}


def per_item_f1(items, src):
    """自动探测逐题 f1：先直接键，再看 metrics 子表。→ (dict|None, 键名)"""
    for it in items.values():
        for k in F1_KEYS:
            if k in it and isinstance(it[k], (int, float)):
                return {key: it[k] for key, it in items.items()}, "%s.%s" % (src, k)
        m = it.get("metrics")
        if isinstance(m, dict):
            for k in F1_KEYS:
                if k in m and isinstance(m[k], (int, float)):
                    return {key: m[k] for key, it in items.items()}, "%s.metrics.%s" % (src, k)
        break
    return None, None


def summarize(checks, extra_lines):
    fails = [c for c in checks if c[1] == FAIL]
    na = [c for c in checks if c[1] == NA]
    ok = not fails
    print()
    for line in extra_lines:
        print(line)
    print("VERDICT: %s（%d PASS / %d FAIL / %d UNAVAILABLE）"
          % (PASS if ok else FAIL,
             sum(1 for c in checks if c[1] == PASS), len(fails), len(na)))
    if ok:
        print("[BATCH-EQUIV] PASS → 其余三套用 batch=4")
    else:
        print('[BATCH-EQUIV] FAIL → 全部 batch=1，报告写"提速未采用"')
    return 0 if ok else 1


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = [a for a in argv[1:]]
    out_path = ""
    why = False
    paths = []
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            out_path = args[i + 1]; i += 2
        elif args[i] == "--why":
            why = True; i += 1
        else:
            paths.append(args[i]); i += 1
    if len(paths) != 2:
        print("用法: batch_equiv_compare.py A.json B.json [--out verdict.json] [--why]", file=sys.stderr)
        return 2
    for p in paths:
        if not os.path.isfile(p):
            print("文件不存在: %s" % p, file=sys.stderr)
            return 2

    a, b = load(paths[0]), load(paths[1])
    print("== batch 等价性取证 ==")
    print("A = %s" % paths[0])
    print("B = %s" % paths[1])

    src_a, ia = norm_items(a)
    src_b, ib = norm_items(b)
    checks = []
    lines = []

    # ---- G1 pass 向量 ----
    if not ia or not ib:
        checks.append(("G1 pass 向量", FAIL, "两侧有一侧没有逐题条目（%s/%s）" % (src_a, src_b)))
    else:
        only_a = sorted(set(ia) - set(ib), key=str)
        only_b = sorted(set(ib) - set(ia), key=str)
        mism = [k for k in set(ia) & set(ib) if bool(ia[k].get("pass")) != bool(ib[k].get("pass"))]
        ev = {"items_a": len(ia), "items_b": len(ib),
              "only_a": only_a[:5], "only_b": only_b[:5],
              "pass_diffs": len(mism), "first_diffs": [str(x) for x in mism[:8]],
              "pass_a": sum(1 for v in ia.values() if v.get("pass")),
              "pass_b": sum(1 for v in ib.values() if v.get("pass"))}
        ok = not only_a and not only_b and not mism
        checks.append(("G1 pass 向量", PASS if ok else FAIL, json.dumps(ev, ensure_ascii=False)))
        if mism:
            lines.append("  pass 分歧题号（前8）：%s" % [str(x) for x in mism[:8]])

    # ---- G2 mean_f1 完全相同（浮点 ==）----
    sa, sb = a.get("summary") or {}, b.get("summary") or {}
    for key in ("mean_f1", "mean_ref_recall"):
        va, vb = sa.get(key), sb.get(key)
        if va is None and vb is None:
            checks.append(("G2 %s" % key, NA, "两侧均无该指标"))
            continue
        if va is None or vb is None:
            checks.append(("G2 %s" % key, FAIL, "一侧缺失：A=%r B=%r" % (va, vb)))
            continue
        same = (float(va) == float(vb))
        delta = abs(float(va) - float(vb))
        ev = {"A": va, "B": vb, "delta": "%.18g" % delta}
        checks.append(("G2 %s" % key, PASS if same else FAIL, json.dumps(ev, ensure_ascii=False)))
        if not same:
            lines.append("  %s 差值 |Δ|=%.18g（判定用 ==，容差仅显示）" % (key, delta))

    # ---- G3 逐题 f1 向量 ----
    fa, ka = per_item_f1(ia, src_a or "?")
    fb, kb = per_item_f1(ib, src_b or "?")
    if fa is None or fb is None:
        checks.append(("G3 逐题 f1 向量", NA,
                       "产物无逐题 f1（探测键 %s）：%s vs %s → 用 G3a/G3b/G3c 同源硬代理"
                       % ("/".join(F1_KEYS), ka or "无", kb or "无")))
    else:
        keys = set(fa) | set(fb)
        diffs = [k for k in keys if float(fa.get(k, float("nan"))) != float(fb.get(k, float("nan")))]
        ev = {"key": ka, "keys_b": kb, "items": len(keys), "f1_diffs": len(diffs),
              "first_diffs": [str(x) for x in sorted(diffs, key=str)[:8]]}
        checks.append(("G3 逐题 f1 向量", PASS if not diffs else FAIL,
                       json.dumps(ev, ensure_ascii=False)))

    # ---- G3a/G3b 逐题文本 / 字数（生成是否分叉的硬证据）----
    ra = {k: v for k, v in (a.get("rows") or []) and enumerate(a.get("rows") or [])}
    rows_a = (a.get("rows") or [])
    rows_b = (b.get("rows") or [])
    if rows_a and rows_b:
        ma = {int(r.get("i", j)): r for j, r in enumerate(rows_a) if isinstance(r, dict)}
        mb = {int(r.get("i", j)): r for j, r in enumerate(rows_b) if isinstance(r, dict)}
        common = set(ma) & set(mb)
        hd = [k for k in common if (ma[k].get("head") or "") != (mb[k].get("head") or "")]
        cd = [k for k in common if ma[k].get("chars") != mb[k].get("chars")]
        checks.append(("G3a 逐题 head 文本", PASS if not hd else FAIL,
                       json.dumps({"diffs": len(hd), "first": sorted(hd)[:8]}, ensure_ascii=False)))
        checks.append(("G3b 逐题 chars", PASS if not cd else FAIL,
                       json.dumps({"diffs": len(cd), "first": sorted(cd)[:8]}, ensure_ascii=False)))
    else:
        checks.append(("G3a 逐题 head 文本", NA, "产物无 rows[]"))
        checks.append(("G3b 逐题 chars", NA, "产物无 rows[]"))

    # ---- G3c 计数 ----
    cnt_keys = ("n", "n_ok", "n_err", "n_empty")
    ca = {k: sa.get(k) for k in cnt_keys}
    cb = {k: sb.get(k) for k in cnt_keys}
    checks.append(("G3c 计数", PASS if ca == cb else FAIL,
                   json.dumps({"A": ca, "B": cb}, ensure_ascii=False)))

    # ---- G4 顶层协议/尺子一致 ----
    pa, pb = a.get("protocol") or {}, b.get("protocol") or {}
    ga = {"suite": a.get("suite"), "judge": a.get("judge"),
          "data_sha16": (a.get("data") or {}).get("sha16"),
          "max_tokens": (a.get("eval_meta") or {}).get("max_tokens") or pa.get("max_tokens"),
          "tools": pa.get("tools")}
    gb = {"suite": b.get("suite"), "judge": b.get("judge"),
          "data_sha16": (b.get("data") or {}).get("sha16"),
          "max_tokens": (b.get("eval_meta") or {}).get("max_tokens") or pb.get("max_tokens"),
          "tools": pb.get("tools")}
    diffs = {k: (ga[k], gb[k]) for k in ga if ga[k] != gb[k]}
    checks.append(("G4 同参同尺", PASS if not diffs else FAIL,
                   json.dumps({"A": ga, "B": gb, "diffs": diffs}, ensure_ascii=False)))

    print()
    for name, st, ev in checks:
        print("%-18s %-12s %s" % (name, st, ev))

    if why:
        lines.append("  [why] 浮点 == 不误伤：f1/mean_f1 由文本派生；生成完全相同 → 同一串浮点运算 →"
                     " 按位相同；浮点不同即文本已不同 = 真实分歧，必须 FAIL（容差只用于显示）")

    code = summarize(checks, lines)

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        verdict = {"conclusion": "[BATCH-EQUIV] %s" % (PASS if code == 0 else FAIL),
                   "a": paths[0], "b": paths[1],
                   "checks": [{"name": n, "status": s, "evidence": e} for n, s, e in checks],
                   "note": "G3 逐题 f1 在产物无该字段时记 UNAVAILABLE，由 G3a/G3b/G3c 代理"}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(verdict, f, ensure_ascii=False, indent=1)
        print("  写 → %s" % out_path)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
