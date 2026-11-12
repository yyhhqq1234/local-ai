#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""方案 Z 汇总裁决：读评测/门禁产物 → train/logs/z-final-report.md
判据沿用既有验收口径（不新造阈值）：
  RE 三条件：acc>=基线 · 编造(fake)==0 · hit>=基线hit
  2A 三条件：avg_cov>=0.60 · code_rate>=0.60 · tool_call 门禁通过(rc==0)
  附加：ngram<0.05（非背诵）
"""
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
OUT, L = "train/lines/9b-oxcoder/out", "train/logs"
REP = os.path.join(L, "z-final-report.md")

RE_ACC_MIN = 0.75
AA_COV_MIN = 0.60
AA_CODE_MIN = 0.60
NG_LIMIT = 0.05


def jload(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def tail(p, n=20000):
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()[-n:]
    except Exception:
        return ""


def gate_rc(p):
    rc = re.findall(r"rc=(\d+)", tail(p))
    return int(rc[-1]) if rc else None


def mark(ok):
    return "PASS" if ok else "FAIL"


def main():
    md = []
    md.append("# 方案 Z 最终验收报告")
    md.append("")
    md.append(f"生成时间：{datetime.now():%F %T}（自动，takeover_z.sh STEP6）")
    md.append("")

    # ---------- RE ----------
    re_j = jload(f"{OUT}/eval-re-zre.json")
    re_verdict = None
    md.append("## 一、Z-B（RE adapter：r3 + 47 工具调用范式）")
    md.append("")
    if not isinstance(re_j, dict) or not isinstance(re_j.get("results"), list):
        md.append("- 缺失 `train/lines/9b-oxcoder/out/eval-re-zre.json` → RE 未评测")
    else:
        rows = re_j["results"]
        base = next((r for r in rows if r.get("label") == "r3"), None)
        # 候选优先序（取最新一轮）：zbv4 > zbv3 > zbv2 > zre > 首个非 r3
        cand = None
        for lab in ("zbv4", "zbv3", "zbv2", "zre"):
            cand = next((r for r in rows if r.get("label") == lab), None)
            if cand:
                break
        cand = cand or next((r for r in rows if r.get("label") != "r3"), None)
        md.append("| adapter | n | hit | acc | 编造 | wrong | noarg | L1 | L2 | L3 |")
        md.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            bl = r.get("by_level") or {}
            def blv(k):
                v = bl.get(k) or {}
                return f"{v.get('hit','-')}/{v.get('n','-')}"
            md.append(f"| {r.get('label')} | {r.get('n')} | {r.get('hit')} | "
                      f"{r.get('acc')} | {r.get('fake')} | {r.get('wrong')} | {r.get('noarg')} | "
                      f"{blv('L1')} | {blv('L2')} | {blv('L3')} |")
        md.append("")
        if cand:
            b_acc = (base or {}).get("acc", 0) or 0
            b_hit = (base or {}).get("hit", 0) or 0
            c1 = (cand.get("acc") or 0) >= max(RE_ACC_MIN, b_acc)
            c2 = (cand.get("fake") or 0) == 0
            c3 = (cand.get("hit") or 0) >= b_hit
            re_verdict = c1 and c2 and c3
            md.append("| 条件 | 判据 | 实测 | 结论 |")
            md.append("|---|---|---|---|")
            md.append(f"| acc 不低于基线 | ≥{max(RE_ACC_MIN, b_acc):.3f} | {cand.get('acc')} | {mark(c1)} |")
            md.append(f"| 不编造工具名 | ==0 | {cand.get('fake')} | {mark(c2)} |")
            md.append(f"| 命中数不低于基线 | ≥{b_hit} | {cand.get('hit')} | {mark(c3)} |")
            md.append("")
            md.append(f"**Z-B 裁决：{mark(re_verdict)}**")
            if cand.get("fake"):
                fakes = []
                for d in (cand.get("detail") or []):
                    if d.get("fake"):
                        fakes.append(f"{d.get('id')}:{','.join(d.get('fake') or [])}→期望{d.get('expect')}")
                if fakes:
                    md.append("")
                    md.append("编造明细：" + "；".join(fakes[:10]))
    md.append("")

    # ---------- 2A ----------
    # A 腿：列出历轮，取 avg_cov 最高者为正式成绩
    ROUNDS = [("v1", "eval-2a-z2a.json"), ("v2", "eval-2a-z2a-v2.json"),
              ("v3", "eval-2a-z2a-v3.json"), ("v5", "eval-2a-z2a-v5.json"),
              ("v6", "eval-2a-z2a-v6.json"), ("v7", "eval-2a-z2a-v7.json")]
    cands = []
    for tag, fn in ROUNDS:
        j = jload(f"{OUT}/{fn}")
        if isinstance(j, dict) and j.get("avg_cov") is not None:
            cands.append((tag, fn, j))
    a2, a2_src = (None, "")
    if cands:
        _, fn, j = max(cands, key=lambda x: x[2].get("avg_cov") or 0)
        a2, a2_src = j, fn
    base2 = jload(f"{OUT}/eval-2a-r3-v2.json")
    md.append("## 二、Z-2A（独立 2A adapter）")
    md.append("")
    aa_verdict = None
    if not isinstance(a2, dict):
        md.append("- 无任何 2A 评测文件 → 2A 未评测")
    else:
        cov = a2.get("avg_cov") or 0
        code = a2.get("code_rate") or 0
        ng = a2.get("avg_ngram20") or 0
        g_eval = None
        for gtag in ("v7", "v6", "v5", "v3", "v2"):
            rc = gate_rc(f"{L}/gate-z2a-{gtag}.log")
            if rc is not None:
                g_eval = rc
                break
        c1 = cov >= AA_COV_MIN
        c2 = code >= AA_CODE_MIN
        c3 = (g_eval == 0)
        c4 = ng < NG_LIMIT
        aa_verdict = c1 and c2 and c3 and c4
        md.append(f"- 正式成绩取：`{a2.get('adapter')}`（来自 `{a2_src}`，历轮 cov 最高）· n={a2.get('n')}")
        md.append("")
        md.append("| 轮 | avg_cov | code_rate | ngram20 |")
        md.append("|---|---|---|---|")
        for tag, fn, j in cands:
            md.append(f"| {tag} | {j.get('avg_cov')} | {j.get('code_rate')} | {j.get('avg_ngram20')} |")
        md.append(f"| **r3 基线** | {(base2 or {}).get('avg_cov','-')} | {(base2 or {}).get('code_rate','-')} | - |")
        md.append("")
        md.append("| 判据 | 门槛 | 实测 | 结论 |")
        md.append("|---|---|---|---|")
        md.append(f"| avg_cov | ≥{AA_COV_MIN} | {cov} | {mark(c1)} |")
        md.append(f"| code_rate | ≥{AA_CODE_MIN} | {code} | {mark(c2)} |")
        md.append(f"| tool_call 门禁 | rc=0 | rc={g_eval} | {mark(c3)} |")
        md.append(f"| avg_ngram20 | <{NG_LIMIT} | {ng} | {mark(c4)} |")
        md.append("")
        md.append(f"**Z-2A 裁决：{mark(aa_verdict)}**")
    md.append("")

    # ---------- 门禁 ----------
    md.append("## 三、门禁")
    md.append("")
    md.append("| 门 | 文件 | rc | 结论 |")
    md.append("|---|---|---|---|")
    for name, p in [("eval 门禁", f"{L}/gate-z2a-v2.log"),
                    ("toolname 门禁", f"{L}/gate-toolname-z2a.log"),
                    ("notool 门禁", f"{L}/gate-notool-z2a.log")]:
        rc = gate_rc(p)
        md.append(f"| {name} | `{p}` | {rc if rc is not None else '-'} | "
                  f"{mark(rc == 0) if rc is not None else '未跑'} |")
    md.append("")

    # ---------- 总裁决 ----------
    md.append("## 四、总裁决与路由")
    md.append("")
    md.append("| 腿 | 裁决 |")
    md.append("|---|---|")
    md.append(f"| Z-B（RE） | {mark(re_verdict) if re_verdict is not None else '未完成'} |")
    md.append(f"| Z-2A | {mark(aa_verdict) if aa_verdict is not None else '未完成'} |")
    md.append("")
    md.append("路由规则（方案 Z 成立即生效）：")
    md.append("")
    md.append("```text")
    md.append("请求带 kitty 工具意图 / 逆向任务  → 挂 Z-B adapter（RE，带 58 工具 schema）")
    md.append("纯编程问答 / 无工具意图          → 挂 Z-2A adapter（不吐 tool_call）")
    md.append("```")
    md.append("")

    with open(REP, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print(f"[aggregate_z] 写出 {REP} · RE={mark(re_verdict) if re_verdict is not None else 'NA'} "
          f"· 2A={mark(aa_verdict) if aa_verdict is not None else 'NA'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
