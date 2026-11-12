#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_cont_pos.py — 从已有创作正样本切出「接着写」多轮样本（修 R2：正样本太短）

为什么这么做
  NSFW 正样本 p50 只有约 400 token，模型在 NSFW 模式下拿不到「写多深/写多长」的锚点。
  用本地引擎批量扩写 3,400 条 × 700 token 在 10 tok/s 下要 60+ 小时，不现实。
  但现有正文本身就有大量 600–2000 字的长段：把它按段落边界切成
    user: 前半段 + 「接着这段写下去。」
    assistant: 后半段
  等于零成本把「连续创作」监督信号的 token 量翻倍，而且训练的是真续写行为。

守卫（任一不满足即丢弃，绝不造脏数据）
  · 后半段 ≥ --min-tail 字符
  · 两段都不含编排词（识别到/先判断/落点/拆解/可执行/可交付/同步进度/常规模式）
  · 后半段首字符不是括号/「当前」/「模式」
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
ORCH = ("识别到", "先判断", "落点", "拆解", "可执行", "可交付", "同步进度", "常规模式", "模式：")
BAD_HEAD = ("当前", "模式", "（", "(", "【", "[")
TAIL_ASK = "\n\n接着这段写下去。"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="含门控正样本的 jsonl（gen4-gate.jsonl）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-head", type=int, default=250)
    ap.add_argument("--min-tail", type=int, default=250)
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--max-rep", type=float, default=0.30,
                    help="assistant 8-gram 重复率上限（C19 复读门禁）")
    a = ap.parse_args()

    st = collections.Counter()
    out = []
    seen = set()

    for line in open(a.data, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        msgs = row.get("messages") or []
        sys_txt = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if "NSFW" not in sys_txt:
            continue
        ans = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant").strip()
        usr = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user").strip()
        if len(ans) < a.min_head + a.min_tail:
            st["short"] += 1
            continue

        paras = [p for p in re.split(r"\n\s*\n", ans) if p.strip()]
        if len(paras) < 2:
            # 中文正文常常整段没有空行：退化为按句末切，取最接近 45% 的位置
            sents = [s for s in re.split(r"(?<=[。！？…”』」])", ans) if s and s.strip()]
            if len(sents) < 4:
                st["no_para"] += 1
                continue
            acc, cut = 0, 0
            for i, s in enumerate(sents[:-1]):
                acc += len(s)
                if acc >= len(ans) * 0.45:
                    cut = i + 1
                    break
            paras = ["".join(sents[:cut]), "".join(sents[cut:])]
            st["sent_split"] += 1

        # 找最接近 45% 的段落边界
        total = sum(len(p) for p in paras) + 2 * (len(paras) - 1)
        target = total * 0.45
        acc, cut = 0, -1
        for i, p in enumerate(paras[:-1]):
            acc += len(p) + 2
            if acc >= target:
                cut = i + 1
                break
        if cut <= 0:
            cut = max(1, len(paras) // 2)

        head = "\n\n".join(paras[:cut]).strip()
        tail = "\n\n".join(paras[cut:]).strip()
        if len(head) < a.min_head or len(tail) < a.min_tail:
            st["bad_split"] += 1
            continue
        if any(w in head[-200:] or w in tail[:200] for w in ORCH):
            st["orch"] += 1
            continue
        if tail[0] in BAD_HEAD:
            st["tail_head"] += 1
            continue
        flat = re.sub(r"\s+", "", tail)
        if len(flat) > 60:
            grams = [flat[i:i + 8] for i in range(len(flat) - 7)]
            rep = 1 - len(set(grams)) / len(grams)
            if rep > a.max_rep:
                st["tail_repetitive"] += 1
                continue
            if flat[:20] in re.sub(r"\s+", "", head)[-80:]:
                st["tail_echo"] += 1
                continue

        key = hashlib.blake2b((head[:400] + "|" + tail[:200]).encode(), digest_size=8).hexdigest()
        if key in seen:
            st["dup"] += 1
            continue
        seen.add(key)

        out.append({
            "messages": [
                {"role": "system", "content": POS_SYS},
                {"role": "user",
                 "content": "%s%s" % (head, TAIL_ASK) if not usr else
                            "%s\n\n%s%s" % (usr, head, TAIL_ASK)},
                {"role": "assistant", "content": tail},
            ],
            "tools": None,
            "meta": {"cat": "cont"},
        })
        st["ok"] += 1
        if a.max_rows and len(out) >= a.max_rows:
            break

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(a.out, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    print(f"[out] {a.out}  {len(out)} 行  "
          f"{os.path.getsize(a.out)/(1<<20):.1f} MiB  sha {h.hexdigest()[:16]}")
    for k in sorted(st):
        print(f"  {k:12s} {st[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
