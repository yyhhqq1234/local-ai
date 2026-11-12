#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gate_paired.py —— 门控数据「同一 prompt 双模式」配对重建（决定 recall 能否 ≥0.90）

实测问题（2026-11-02）
  原始集 gen3_1p   ：pos 唯一 6,999 / neg 唯一 6,999 / **交集 6,999（100% 配对）**
  清洗后 p3/p4/p6  ：pos 3,518 / neg 3,481 / **交集 0（配对全丢）**
  我重建的 gen5/6  ：pos 4,407 / neg 3,476 / **交集 0**

  配对丢了意味着：模型看到的不是「同一个请求，换个模式该给出不同行为」，
  而是「A 类写法该写正文，B 类写法该拒绝」——它学的是**内容分类**，不是**开关**。
  这解释了为什么 L1 / R / P0 / P1 四条 arm 的 recall 全都卡在 0.375：数据层面就没教过开关。

做法
  以正样本的 prompt 为基准（这些 prompt 是"露骨续写"型，正是门控要打的靶），
  对每条 prompt 造一条常规模式样本：user 文本**逐字相同**，system 换成常规，assistant 用统一短拒绝。
  → 每条 prompt 在训练里出现两次，唯一差异就是 system 串 → 开关变成可学信号。

用法
  python build_gate_paired.py --pos gen5-gate.jsonl --out gen7-gate.jsonl [--ratio 1.0]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys

POS_SYS = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
NEG_SYS = "模式：常规（未授权成人向内容）。不含露骨性描写。"
REFUSAL = ("当前为常规模式（未授权成人向内容），不输出露骨性描写。\n\n"
           "可以按这个口径继续：同题材的非露骨版本 —— 情节推进、氛围与心理描写，性内容留白处理。")
ORCH = re.compile(r"(识别到|先判断|落点|拆解|可执行|可交付|同步进度|常规模式|不输出|"
                  r"（上文）|【成人向】|继续写下去|接着这段)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", required=True, help="只取正样本的数据集（gen5-gate.jsonl）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratio", type=float, default=1.0, help="pos:neg 比例（1.0 = 1:1）")
    a = ap.parse_args()

    st = collections.Counter()
    pos_rows = []
    seen = set()

    for line in open(a.pos, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        msgs = r["messages"]
        sysm = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if "NSFW" not in sysm:
            continue
        user = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
        asst = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant").strip()
        if not user.strip() or not asst:
            st["pos_bad"] += 1
            continue
        if ORCH.search(asst[:200]):
            st["pos_orch"] += 1
            continue
        h = hashlib.blake2b(user.encode(), digest_size=8).hexdigest()
        if h in seen:
            st["pos_dup"] += 1
            continue
        seen.add(h)
        pos_rows.append({"messages": [{"role": "system", "content": POS_SYS},
                                      {"role": "user", "content": user},
                                      {"role": "assistant", "content": asst}],
                         "tools": None, "meta": {"cat": "cont"}})

    neg_rows = []
    for p in pos_rows:
        user = p["messages"][1]["content"]
        neg_rows.append({"messages": [{"role": "system", "content": NEG_SYS},
                                      {"role": "user", "content": user},
                                      {"role": "assistant", "content": REFUSAL}],
                         "tools": None, "meta": {"cat": "scene"}})

    reps = max(1, int(round(a.ratio)))
    out = pos_rows * reps + neg_rows
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    hh = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            hh.update(c)

    pu = {r["messages"][1]["content"] for r in pos_rows}
    nu = {r["messages"][1]["content"] for r in neg_rows}
    print(f"[out] {a.out}  {len(out)} 行  {os.path.getsize(a.out)/(1<<20):.1f} MiB  sha {hh.hexdigest()[:16]}")
    print(f"[pair] pos 唯一 {len(pu)} / neg 唯一 {len(nu)} / 交集 {len(pu & nu)} "
          f"= 配对率 {len(pu & nu)/max(1,len(pu))*100:.1f}%")
    print(f"[ratio] pos {len(pos_rows)*reps} : neg {len(neg_rows)}")
    print(f"[stat] {dict(st)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
