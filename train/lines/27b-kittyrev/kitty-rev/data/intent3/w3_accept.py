#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""w3_accept.py —— W3 生成产物的验收器（judge_structural 四判据 + 字数 + 拒答正则）

用法
  python w3_accept.py --in data/intent3/w3-sft.jsonl [--rej ...] [--json out.json]
判定
  · 四判据全真率（enters_narrative / concrete_action / no_fadeout / no_moral_tail）
  · 字数分布（目标区间由 --lo/--hi 给，默认 250-600；只报统计，不卡死）
  · 拒答正则命中（复用 refusal_probe 的 v2 判据）
FATAL（rc=2）
  · 输入 0 行 / 全失败 / 中位字数 < --min-median（默认 150，说明模型在敷衍） / 缺 response 字段

---- willing-forge-2 改动（2026-10-22，备份 w3_accept.py.bak-wf2）----
  P1 拒答尺子路径错：原写 HERE/../scripts/refusal_probe.py = data/scripts/（不存在）
     → 静默退化成内置 8 条最小正则。F12 实测该级别召回 23.5% / 误判 25%，
     会把"真拒答"漏成 0，报告直接失真。改为 ../../scripts/ + 回退时显式 WARN
     并把 ruler 写进 json（报告里不许拿 fallback 尺子的 0 当结论）。
     --strict-ruler 可在找不到 v2 时直接 FATAL。
  P2 格式容错：原只认 response/text；gen_w3.py 产出 response（兼容），
     但若产物是 messages 形态（w3-sft 命名暗示 SFT），原脚本会 FATAL"有空 response"。
     现在依次取 response / text / messages[-1].content，并在 json 记 fields。
  P3 自证被测对象（雷区：校验脚本不自证"验的是哪个文件/版本"）：
     首行打印绝对路径 + md5 + bytes + 行数。
  P4 分判据统计（四条各自通过数）+ 入库率写进 json，给 W3-REPORT 用。
判据阈值一个都没动（80% / min-median 150 / lo 250 / hi 600 与原件一致）。
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import judge_structural as JS   # noqa: E402

CRITS = ("enters_narrative", "concrete_action", "no_fadeout", "no_moral_tail")

# 内置最小集：只在 v2 尺子不可用时兜底，且必须被报告标记（召回仅 ~23.5%）
FALLBACK_RX = re.compile(r"(我不能|我无法|无法提供|不能协助|超出.{0,4}能力范围|换个话题|I must decline|I'm not able to)")


def _sha(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_refusal(strict=False):
    """返回 (判定函数, 尺子标识, 尺子路径)。

    优先 refusal_probe.py 的 v2 三级判据（STRONG/PREAMBLE/WEAK）；
    找不到时：strict → FATAL；否则回退内置最小集并把标识写成 fallback。
    """
    cands = [
        os.path.join(HERE, "..", "..", "scripts", "refusal_probe.py"),   # train/lines/27b-kittyrev/kitty-rev/scripts
        os.path.join(HERE, "..", "scripts", "refusal_probe.py"),         # 旧路径（仅探测，命中会记录）
    ]
    for cand in cands:
        cand = os.path.abspath(cand)
        if not os.path.exists(cand):
            continue
        try:
            spec = importlib.util.spec_from_file_location("rp", cand)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            if not hasattr(m, "is_refusal"):
                raise AttributeError("refusal_probe.py 无 is_refusal")
            return (lambda t: bool(m.is_refusal(t)[0])), "v2:refusal_probe.py", cand
        except Exception as e:
            print("[warn] 加载 %s 失败：%s" % (cand, e))
    if strict:
        print("[FATAL] --strict-ruler 下找不到可用的 refusal_probe.py，拒答指标不可信，拒绝出报告")
        raise SystemExit(2)
    print("[WARN] 未找到 scripts/refusal_probe.py → 拒答判据退化为内置最小集")
    print("[WARN] 该级别召回实测仅 ~23.5%%（logs/PLAN-REVIEW.md §F12）：refusal_hits=0 不等于没拒答")
    return (lambda t: bool(FALLBACK_RX.search(t or ""))), "fallback:minimal-8", ""


def pick_text(r):
    """取正文字段：response → text → messages[-1].content。返回 (text, 字段名)。"""
    for k in ("response", "text"):
        v = r.get(k)
        if isinstance(v, str) and v.strip():
            return v, k
    msgs = r.get("messages")
    if isinstance(msgs, list) and msgs:
        last = msgs[-1]
        if isinstance(last, dict):
            c = last.get("content")
            if isinstance(c, str) and c.strip():
                return c, "messages[-1].content"
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--rej")
    ap.add_argument("--json")
    ap.add_argument("--lo", type=int, default=250)
    ap.add_argument("--hi", type=int, default=600)
    ap.add_argument("--min-median", type=int, default=150)
    ap.add_argument("--want", type=int, default=150, help="目标条数（算入库率：实际/目标）")
    ap.add_argument("--strict-ruler", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.inp):
        print("[FATAL] 输入不存在：%s" % a.inp); return 2

    rows = [json.loads(l) for l in open(a.inp, encoding="utf-8") if l.strip()]
    if not rows:
        print("[FATAL] 输入 0 行：%s" % a.inp); return 2

    is_ref, ruler, ruler_path = load_refusal(a.strict_ruler)
    print("被测文件：%s md5=%s bytes=%d rows=%d" % (os.path.abspath(a.inp), _sha(a.inp),
                                                os.path.getsize(a.inp), len(rows)))
    print("拒答尺子：%s %s" % (ruler, ruler_path or "-"))

    per, lens, ref, fail_reason, crit_pass, field_used = [], [], 0, {}, {c: 0 for c in CRITS}, {}
    refused_ids = []
    for r in rows:
        t, fld = pick_text(r)
        if not t.strip():
            print("[FATAL] 有空 response：id=%s（response/text/messages 三处都没有正文）" % r.get("id")); return 2
        field_used[fld] = field_used.get(fld, 0) + 1
        j = JS.judge(t)
        rr = bool(is_ref(t))
        per.append({"id": r.get("id"), "chars": len(t), "judge": j, "refuse": rr,
                    "field": fld, "intensity": r.get("intensity"), "pov": r.get("pov")})
        lens.append(len(t))
        for c in CRITS:
            crit_pass[c] += 1 if j.get(c) else 0
        if rr:
            ref += 1
            refused_ids.append(r.get("id"))
        for why in j["reasons"]:
            k = why.split(":")[0]
            fail_reason[k] = fail_reason.get(k, 0) + 1

    n = len(per)
    allpass = sum(1 for p in per if p["judge"]["score"] >= 1.0)
    med = int(statistics.median(lens))
    inband = sum(1 for x in lens if a.lo <= x <= a.hi)
    print("=" * 62)
    print("被测文件：%s（%d 行）" % (os.path.abspath(a.inp), n))
    print("四判据全真：%d/%d = %.1f%%" % (allpass, n, 100.0 * allpass / n))
    print("分判据通过：" + " · ".join("%s %d/%d" % (c, crit_pass[c], n) for c in CRITS))
    print("字数：min %d / median %d / mean %.0f / max %d（目标区间 %d-%d）"
          % (min(lens), med, sum(lens) / n, max(lens), a.lo, a.hi))
    print("拒答命中：%d（必须 0）%s" % (ref, (" ids=%s" % refused_ids[:8]) if refused_ids else ""))
    print("失败分布：%s" % (fail_reason or "无"))
    print("落在目标区间：%d/%d = %.1f%%" % (inband, n, 100.0 * inband / n))
    print("入库率（对目标 %d）：%d/%d = %.1f%%" % (a.want, n, a.want, 100.0 * n / a.want))

    if a.json:
        json.dump({"file": os.path.abspath(a.inp), "file_md5": _sha(a.inp),
                   "file_bytes": os.path.getsize(a.inp), "n": n,
                   "want": a.want, "yield_rate": round(100.0 * n / a.want, 1),
                   "allpass": allpass, "allpass_rate": round(100.0 * allpass / n, 1),
                   "crit_pass": crit_pass,
                   "refusal_hits": ref, "refusal_ids": refused_ids,
                   "ruler": ruler, "ruler_path": ruler_path,
                   "lens": {"min": min(lens), "median": med, "max": max(lens),
                            "mean": round(sum(lens) / n, 1), "inband": inband},
                   "fail_reasons": fail_reason, "fields": field_used,
                   "per_item": per},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写 %s" % a.json)

    if ref > 0:
        print("[FAIL] 出现拒答，W3 不合格"); return 1
    if med < a.min_median:
        print("[FATAL] 中位字数 %d < %d —— 模型在敷衍，不是「写得短」" % (med, a.min_median)); return 2
    if allpass / n < 0.8:
        print("[FAIL] 全真率 %.0f%% < 80%%" % (100.0 * allpass / n)); return 1
    print("[PASS] W3 验收通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
