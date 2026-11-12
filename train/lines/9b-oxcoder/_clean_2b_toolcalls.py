#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清洗 2B 门控集：去掉三类外部工具语法/日志污染

来源诊断（2026-11-01）：
  2B 数据 = gate-pos 13951 + gate-neg 8411 + ctl 3500
  gate-pos/neg 干净（0 tool_call），但 ctl（常规对照，取自 OpenHands SWE 轨迹）带：
    ① `[CALL execute_bash] {...}` / `[CALL str_replace_editor] {...}` 调用行
    ② `[Command finished with exit code 0]` / `[Python interpreter: ...]` 执行日志
    ③ `【assistant】` / `【user】` 角色标记（已知污染 B11）
    ④ 少量 `<tool_call>…</tool_call>`（含未闭合）

处置：逐行清洗 assistant 正文，剩余不足 40 字符的行整行丢弃；原文件备份 .bak-toolclean
"""
import io
import json
import os
import re
import sys

P = "train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl"
MIN_KEEP = 40

RULES = [
    (re.compile(r"\s*<tool_call>.*?</tool_call>\s*", re.S), "\n"),      # 成对 tool_call
    (re.compile(r"\s*<tool_call>.*\Z", re.S), "\n"),                    # 未闭合 tool_call
    (re.compile(r"\[CALL\s+[a-z_]+\][^\n]*"), ""),                      # 内联/行首 [CALL xxx] {...}
    (re.compile(r"\[(The command completed|Command finished|Python interpreter|Current working directory|Process exited)[^\]\n]*\]", re.I), ""),
    (re.compile(r"【(assistant|user|system|observation)】"), ""),        # 角色标记 B11（含 observation）
]


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "assistant")


def main():
    if not os.path.exists(P):
        print(f"[FATAL] 缺 {P}")
        return 1
    bak = P + ".bak-toolclean"
    if not os.path.exists(bak):
        io.open(bak, "w", encoding="utf-8").write(io.open(P, encoding="utf-8").read())
        print(f"[backup] {bak}")

    rows_in = rows_out = touched = dropped = 0
    with io.open(P, encoding="utf-8") as f, io.open(P + ".tmp", "w", encoding="utf-8") as g:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows_in += 1
            o = json.loads(line)
            changed = False
            for m in o.get("messages", []):
                # 所有 role 都清（observation/tool 里也会带角色标记与执行日志）
                c = m.get("content") or ""
                nc = c
                for pat, rep in RULES:
                    nc = pat.sub(rep, nc)
                nc = re.sub(r"\n{3,}", "\n\n", nc).strip()
                if nc != c.strip():
                    changed = True
                    m["content"] = nc
            if changed:
                touched += 1
            if len(asst(o)) < MIN_KEEP:
                dropped += 1
                continue
            g.write(json.dumps(o, ensure_ascii=False) + "\n")
            rows_out += 1
    os.replace(P + ".tmp", P)
    print(f"[done] 输入 {rows_in} · 清洗 {touched} 行 · 丢弃 {dropped} · 输出 {rows_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
