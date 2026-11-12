#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prerender_gen4.py — 本机预渲染成 {"text": ...}，绕开远端 HF datasets 的 schema 推断

为什么（2026-11-02 实测）
  远端 datasets.load_dataset("json", ...) 直接炸：
    DatasetGenerationError: An error occurred while generating the dataset
  原因：gen4 的 schema 不均匀 —— tools 有的是 list 有的是 null，
        messages 里有的带 tool_calls、有的不带（嵌套 struct 可选键）
        HF json builder 用前若干行推断 schema，遇到不一致就整体失败
  → 最稳的解法：本机用同一个 tokenizer 直接渲染成 {"text": ...}，远端只做纯文本 SFT。
    渲染确定性由「同一份 base tokenizer + chat_template」保证，且远端不再需要解析嵌套结构。

守卫
  · 渲染失败的行直接报错（不静默跳过）
  · 渲染后 token > --ctx 的行直接丢弃并计数
  · 输出 sha256，远端训练前比对

用法
  python prerender_gen4.py --data <gen4.jsonl> --out <gen4-text.jsonl> [--ctx 2048]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys

from transformers import AutoTokenizer

TOK = r"train/lines/27b-kittyrev/base/Qwen3.8-27B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tok", default=TOK)
    ap.add_argument("--ctx", type=int, default=2048)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
    st = collections.Counter()
    lens = []
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fo:
        for i, line in enumerate(open(a.data, encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            msgs = r["messages"]
            tools = r.get("tools")
            try:
                txt = (tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                               add_generation_prompt=False)
                       if tools else
                       tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=False))
            except Exception as e:  # noqa: BLE001
                raise SystemExit(f"[FATAL] 第 {i} 行渲染失败：{type(e).__name__}: {e}")
            n = len(tok(txt, add_special_tokens=False)["input_ids"])
            if n > a.ctx:
                st["over_ctx_dropped"] += 1
                continue
            lens.append(n)
            fo.write(json.dumps({"text": txt}, ensure_ascii=False) + "\n")
            st["ok"] += 1

    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    sha = h.hexdigest()
    open(a.out + ".sha256", "w", encoding="utf-8", newline="\n").write(sha + "\n")
    lens.sort()
    print(f"[out] {a.out}  {st['ok']} 行  {os.path.getsize(a.out)/(1<<20):.1f} MiB  sha {sha[:16]}")
    print(f"[stat] {dict(st)}  tokens p50 {lens[len(lens)//2]} p99 {lens[int(len(lens)*0.99)]} max {lens[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
