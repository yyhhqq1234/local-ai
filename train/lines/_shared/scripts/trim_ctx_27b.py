# -*- coding: utf-8 -*-
"""trim_ctx_27b.py — 按真实渲染长度裁掉超 ctx 的行

为什么必须用渲染后长度：train_kitty.py 走 apply_chat_template(msgs, tools=...)
再 SFTTrainer(max_length=ctx) 截断，所以判据是「渲染后的 token 数」，
不是原始 JSON 字符数，也不是「各字段 token 数相加」（会漏掉模板固定开销）。

用法：
    python trim_ctx_27b.py --data in.jsonl --out out.jsonl --ctx 2048
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter

from transformers import AutoTokenizer

TOK = "train/lines/27b-kittyrev/base/Qwen3.8-27B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--tok", default=TOK)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
    st = Counter()
    keep = []
    over = []
    for i, line in enumerate(open(a.data, encoding="utf-8"), 1):
        d = json.loads(line)
        msgs, tools = d["messages"], d.get("tools")
        try:
            txt = (tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                           add_generation_prompt=False)
                   if tools else
                   tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False))
            n = len(tok(txt, add_special_tokens=False)["input_ids"])
        except Exception as e:  # noqa: BLE001
            st["render_fail_dropped"] += 1
            continue
        if n > a.ctx:
            st["over_ctx_dropped"] += 1
            over.append({"line": i, "tokens": n, "cat": (d.get("meta") or {}).get("cat")})
            continue
        keep.append(line if line.endswith("\n") else line + "\n")
        st["kept"] += 1

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(keep)
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    sha = h.hexdigest()
    open(a.out + ".sha256", "w", encoding="utf-8", newline="\n").write(sha + "\n")
    print(f"[stat] {dict(st)}")
    for o in over[:10]:
        print("  over:", o)
    print(f"[out] {a.out}  {len(keep)} 行  {os.path.getsize(a.out)/(1<<20):.1f} MiB  sha256 {sha[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
