#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rebuild_nsfw_pos.py — 修 A2：创作类正样本「首 token 即正文」，禁编排词，正负 2:1

证据（2026-11-01 实测）
  NSFW 模式下 8 条 trigger 有 4 条 content="" 且 finish=stop，max_tokens 提到 2000 仍空
  reasoning 原文：「先判断这条请求的落点……按设定→冲突→情绪排……把每个情节拆成
  『可执行的动作 + 可交付的结果』」→ 计划完直接 EOS，一句正文都没写
  → 病根是 kitty 编排式元话术跨类别污染了创作类数据

处置（对 gen3_1p6 动手，不重训基座）
  1) 剥掉答案开头的括号元话术：（承接上文…）/（续写中）/（以下为正文）…
  2) 删掉含编排词的引导句：识别到 / 先判断 / 落点 / 拆解 / 可执行 / 可交付 / 同步进度 /
     模式 / 常规模式 / 不输出
  3) 清洗后仍含编排词、或不以正文开头的 → 整行丢弃
  4) 正样本答案太短（< --min-chars）→ 丢弃（现在 p50 只有 ~400 token，锚点偏低）
  5) 正样本 ×N 过采样 → pos:neg ≈ --ratio:1

用法
  python rebuild_nsfw_pos.py --data <gen3_1p6.jsonl> --out <gen4-gate.jsonl> [--ratio 2]
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
CANON_REFUSAL = "当前为常规模式（未授权成人向内容），不输出露骨性描写。"

LEAD_PAREN = re.compile(r"^\s*[（(【\[]\s*[^）)】\]]{0,40}\s*[）)】\]]\s*[\n\r]*")
ORCH = re.compile(r"(识别到|先判断|落点|拆解|可执行|可交付|同步进度|模式：|常规模式|不输出|"
                  r"当前为常规|已授权成人向创作|直接输出正文|（上文）|【成人向】|继续写下去|接着这段)")
BAD_HEAD = ("当前", "模式", "（", "(", "【", "[")


def answer_of(msgs):
    return "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant")


def clean_pos(text: str) -> str:
    t = text.strip()
    # 反复剥开头的括号元话术
    for _ in range(4):
        nt = LEAD_PAREN.sub("", t, count=1)
        if nt == t:
            break
        t = nt.strip()
    # 逐句删掉含编排词的引导句（只从开头连删，避免破坏正文）
    lines = t.split("\n")
    while lines and lines[0].strip() and ORCH.search(lines[0].strip()) \
            and len(lines[0].strip()) < 60:
        lines.pop(0)
    t = "\n".join(lines).strip()
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ratio", type=float, default=2.0)
    ap.add_argument("--min-chars", type=int, default=300)
    a = ap.parse_args()

    st = collections.Counter()
    pos, neg = [], []
    seen = set()

    for line in open(a.data, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        msgs = row.get("messages") or []
        sys_txt = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if not sys_txt.startswith("模式："):
            continue                                  # 非门控行交给别的处理
        ans = answer_of(msgs)
        is_pos = "NSFW" in sys_txt
        if is_pos:
            st["pos_in"] += 1
            c = clean_pos(ans)
            if c != ans.strip():
                st["pos_cleaned"] += 1
            if not c or c[0] in BAD_HEAD:
                st["pos_dropped_head"] += 1
                continue
            if ORCH.search(c[:200]):
                st["pos_dropped_orch"] += 1
                continue
            if len(c) < a.min_chars:
                st["pos_dropped_short"] += 1
                continue
            # 重写 assistant 内容
            for m in msgs:
                if m.get("role") == "assistant":
                    m["content"] = c
            key = hashlib.blake2b(("P|" + "".join(
                (m.get("content") or "") for m in msgs if m.get("role") == "user")).encode(),
                digest_size=8).hexdigest()
            if key in seen:
                st["pos_dup"] += 1
                continue
            seen.add(key)
            pos.append(row)
        else:
            st["neg_in"] += 1
            if CANON_REFUSAL not in ans:
                st["neg_noncanonical"] += 1
                continue
            if ORCH.search(ans.replace(CANON_REFUSAL, "")):
                st["neg_dirty"] += 1
                continue
            ukey = "".join((m.get("content") or "") for m in msgs if m.get("role") == "user")
            key = hashlib.blake2b(("N|" + ukey).encode(), digest_size=8).hexdigest()
            if key in seen:
                st["neg_dup"] += 1
                continue
            seen.add(key)
            neg.append(row)

    reps = max(1, int(round(a.ratio * len(neg) / max(1, len(pos)))))
    out = []
    for i in range(reps):
        out.extend(pos)
    out.extend(neg)
    st["pos_out"] = len(pos) * reps
    st["neg_out"] = len(neg)
    st["reps"] = reps

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    print(f"[out] {a.out}  {len(out)} 行  sha {h.hexdigest()[:16]}")
    for k in sorted(st):
        print(f"  {k:22s} {st[k]}")
    print(f"[ratio] pos:neg = {st['pos_out']}:{st['neg_out']} = "
          f"{st['pos_out']/max(1,st['neg_out']):.2f}:1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
