# -*- coding: utf-8 -*-
"""probe_gen5.py — 打包前的数据门禁（C19 之后新增）

背景：gen4 因为「（上文）」结构标记 + 续写样本占比过高 + lr 3e-5，
      训练出 8-gram 重复率 0.947 的复读模型，白烧 ¥29。
      这些在数据里就能提前测出来，不该等到训练完才发现。

门禁项（任一 FAIL 就不许打包/开训）
  G1 结构性标记残留：assistant 里出现（上文）/【成人向】/接着这段/继续写下去 → 0 容忍
  G2 逐行复读：assistant 8-gram 重复率 >0.30 的行占比 ≤2%
  G3 回声：assistant 开头 20 字出现在 user 尾部 80 字里的行占比 ≤2%
  G4 空答案：0
  G5 门控比例：pos : neg ∈ [1.5, 3.0]
  G6 结构化 tool_calls 行占比 ≥8%
  G7 cont 占比：cont 行 / 门控行 ≤0.35（C19：续写样本不能压过独立创作）

用法：python probe_gen5.py --data <gen5.jsonl>
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys


def flat(t):
    return re.sub(r"\s+", "", t or "")


def rep8(t):
    s = flat(t)
    if len(s) < 60:
        return 0.0
    g = [s[i:i + 8] for i in range(len(s) - 7)]
    return 1 - len(set(g)) / len(g)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()

    MARK = ("（上文）", "【成人向】", "接着这段", "继续写下去")
    n = 0
    mark_hits = rep_bad = echo = empty = 0
    tc_rows = pos = neg = cont = 0
    worst = []
    for line in open(a.data, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        n += 1
        msgs = r["messages"]
        usr = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
        asst = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant")
        sysm = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if any(m.get("tool_calls") for m in msgs):
            tc_rows += 1
        # 合法 agent 首步：assistant 只有 tool_calls、没有正文 —— 不算空答案
        has_tc = any(m.get("tool_calls") for m in msgs)
        if not asst.strip() and not (has_tc and len(msgs) >= 3):
            empty += 1
        if any(k in asst for k in MARK):
            mark_hits += 1
        rp = rep8(asst)
        if rp > 0.30:
            rep_bad += 1
            if len(worst) < 3:
                worst.append((round(rp, 3), asst[:40]))
        f = flat(asst)
        if f[:20] and f[:20] in flat(usr)[-80:]:
            echo += 1
        cat = (r.get("meta") or {}).get("cat", "")
        if sysm.startswith("模式："):
            if "NSFW" in sysm:
                pos += 1
            else:
                neg += 1
        if cat == "cont" and "接着这段写下去" in usr:
            cont += 1

    checks = [
        ("G1 结构标记残留=0", mark_hits == 0, f"{mark_hits} 行"),
        ("G2 复读行占比≤2%", rep_bad / max(1, n) <= 0.02, f"{rep_bad}/{n} = {rep_bad/max(1,n)*100:.2f}%"),
        ("G3 回声行占比≤2%", echo / max(1, n) <= 0.02, f"{echo}/{n} = {echo/max(1,n)*100:.2f}%"),
        ("G4 空答案=0", empty == 0, f"{empty} 行"),
        ("G5 门控 pos:neg∈[1.5,3]", 1.5 <= pos / max(1, neg) <= 3.0,
         f"{pos}:{neg} = {pos/max(1,neg):.2f}:1"),
        ("G6 tool_calls 行≥8%", tc_rows / max(1, n) >= 0.08,
         f"{tc_rows}/{n} = {tc_rows/max(1,n)*100:.2f}%"),
        ("G7 cont 占比≤0.35", cont / max(1, pos + neg) <= 0.35,
         f"{cont}/{pos+neg} = {cont/max(1,pos+neg):.2f}"),
    ]
    print(f"[data] {a.data}  行 {n}")
    fails = 0
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
        fails += 0 if ok else 1
    if worst:
        print("  复读最严重样本:", worst)
    print("=" * 56)
    print(f"门禁结果：{len(checks)-fails}/{len(checks)} PASS"
          + ("" if not fails else "  ❌ 不许打包/开训"))
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
