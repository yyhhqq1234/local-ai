#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""probe_kitty.py —— 测 kitty 工具集的「理解」与「调用」能力（7 题）

判读要点（人工看，不自动打分）：
  · 工具名是否真实（编造不存在的工具 = 幻觉）
  · 参数顺序/名称是否对（S_NEW 的 vt/value/start/stop、P_BACK 的窗口）
  · 是否给出可直接执行的完整指令（调用能力）
  · 是否给出「为什么」（理解能力）
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL = "qwen3.8-27b-ablit-swift15-iq2s"

Q = [
    ("T1 参数记忆", "kitty_ce 的 S_NEW 指令需要几个参数？按顺序写出来，并说明 vt 有哪些合法值。"),
    ("T2 约束理解", "为什么 P_BACK 必须显式给扫描窗口，而不能自动扫全地址空间？"),
    ("T3 设计意图", "kitty_patch 的 patch 操作为什么必须带 expect 参数？不带的后果是什么？"),
    ("T4 边界知识", "kitty_km 的 KM_PW 默认拒绝执行，原因和恢复方式是什么？"),
    ("T5 调用能力", "目标进程 0x7FF6A000 处要读一个 dword。写出 kitty_ce 的完整指令（一条即可）。"),
    ("T6 坑位知识", "MODENUM 返回的模块 size 有时是 0，这时候该用什么办法拿窗口？"),
    ("T7 场景选型", "要找某个血量值的多级指针，从已知地址往回追，kitty 里该用哪个工具、怎么组合？"),
]


def ask(q, max_tokens=420):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": q}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    for name, q in Q:
        try:
            d = ask(q)
            c = (d["choices"][0].get("message", {}).get("content") or "").strip()
        except Exception as e:
            print(f"\n===== {name} =====\nFAIL: {e}")
            continue
        print(f"\n===== {name} =====")
        print(c[:520])
    return 0


if __name__ == "__main__":
    sys.exit(main())
