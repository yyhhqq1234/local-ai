# -*- coding: utf-8 -*-
"""检查 F1 转换后的行长什么样：剥离 tool_call 文本后有没有「凭空讲结果」"""
import json
import re

P = "train/lines/27b-kittyrev/data/versions/gen3_1p4-nsfw-kitty.jsonl"
TC = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
shown = 0
for line in open(P, encoding="utf-8"):
    d = json.loads(line)
    msgs = d["messages"]
    cat = (d.get("meta") or {}).get("cat")
    for m in msgs:
        c = m.get("content") or ""
        if m.get("role") == "assistant" and "<tool_call>" in c:
            blocks = TC.findall(c)
            rest = TC.sub("", c)
            print("=" * 70)
            print("cat:", cat, "| blocks:", len(blocks))
            for b in blocks:
                print("  CALL:", b[:180].replace("\n", " "))
            print("  REST:", rest.strip()[:400].replace("\n", "\\n"))
            shown += 1
            break
    if shown >= 4:
        break
