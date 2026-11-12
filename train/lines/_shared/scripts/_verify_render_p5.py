# -*- coding: utf-8 -*-
"""渲染自检：gen3_1p5 能否被 Qwen chat template 正常渲染（含 tools / tool_calls）

train_kitty.py 的 to_text 会调 tok.apply_chat_template(m, tools=tools)，
任何 arguments 不是 mapping、tool_calls 结构不对都会 TypeError 整轮训练崩。
这里把全量 16,811 行过一遍 template，统计成败并抽 2 条打印。
"""
import json
import sys

from transformers import AutoTokenizer

TOK = "train/lines/27b-kittyrev/base/Qwen3.8-27B"
P = sys.argv[1] if len(sys.argv) > 1 else \
    "train/lines/27b-kittyrev/data/versions/gen3_1p5-nsfw-kitty.jsonl"

tok = AutoTokenizer.from_pretrained(TOK, trust_remote_code=True)
ok = bad = with_tools = with_tc = 0
errs = []
first_tool_row = None
for i, line in enumerate(open(P, encoding="utf-8"), 1):
    d = json.loads(line)
    msgs = d["messages"]
    tools = d.get("tools")
    has_tc = any(m.get("tool_calls") for m in msgs)
    try:
        if tools:
            txt = tok.apply_chat_template(msgs, tools=tools, tokenize=False,
                                          add_generation_prompt=False)
            with_tools += 1
        else:
            txt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        if has_tc:
            with_tc += 1
            if first_tool_row is None:
                first_tool_row = (i, txt)
        ok += 1
    except Exception as e:  # noqa: BLE001
        bad += 1
        if len(errs) < 5:
            errs.append({"line": i, "err": f"{type(e).__name__}: {e}"[:200]})

print(f"render ok={ok} bad={bad} with_tools={with_tools} with_tool_calls={with_tc}")
for e in errs:
    print("  ERR", e)
if first_tool_row:
    i, txt = first_tool_row
    print(f"\n--- 样例行 {i}（含 tool_calls）渲染前 900 字符 ---")
    print(txt[:900])
    print("...")
    print(txt[-500:])
