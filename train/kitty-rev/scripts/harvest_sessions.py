#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""harvest_sessions.py —— 从真实会话解帧（_work/session-audit/s*.jsonl）抽轨迹样本

输入: _work/session-audit/s*.jsonl（DSH 会话事件流，已解帧）
输出:
  data/real_sft.jsonl   正向轨迹（completed 且步数 ≤ --max-steps）
  data/real_neg.jsonl   负向轨迹池（abort / 步数超标），供 DPO rejected 侧构对

抽取规则（不编内容，只做筛选与格式规整）:
  · 以 turn 为单位：turn 内 user/message 作为 prompt，之后按 seq 顺序拼 assistant/tool
  · assistant 的 reasoning 块丢弃（只学行为，不学思考草稿）；text 块保留
  · tool/call → 写成 Qwen 风格 <tool_call>{json}</tool_call> 放进 assistant 正文
  · tool/result → role=tool，超长截断（默认 1200 字符）
  · 步数 = 该 turn 的 tool/call 数；turn/end.reason.kind 决定正负

用法:
  python harvest_sessions.py                 # 扫全部 s*.jsonl
  python harvest_sessions.py --files s9 s11  # 只取指定会话
"""
import argparse
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(HERE))          # Local-AI
AUDIT = os.path.join(ROOT, "_work", "session-audit")
DATA = os.path.join(HERE, "data")

KITTY_RE = re.compile(r"\bkitty_[a-z0-9_]+")


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(x for x in out if x)


def load_events(path):
    ev = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return ev


def build_turns(events):
    """按 turn 聚合 → [{turn, user, msgs, calls, end}]

    注意：user/message 事件**不带 turn 字段**（实测 v4 解帧格式），
    必须按事件顺序归属到最近一次 turn/start 的 turn 号上。
    """
    turns = {}
    cur_turn = None
    for e in events:
        t = e.get("type")
        if not t:
            continue
        d = e.get("data") or {}
        if t == "turn/start":
            cur_turn = d.get("turn")
        tn = d.get("turn")
        if tn is None:
            tn = cur_turn
        if tn is None:
            continue
        cur = turns.setdefault(tn, {"turn": tn, "user": "", "msgs": [], "calls": 0, "end": None, "seqbase": e.get("seq", 0)})
        if t == "user/message" and not cur["user"]:
            cur["user"] = text_of(d.get("content"))
        elif t == "assistant/message":
            m = d.get("message") or {}
            cur["msgs"].append({"kind": "assistant", "text": text_of(m.get("content")), "seq": e.get("seq", 0)})
        elif t == "tool/call":
            cur["msgs"].append({"kind": "call", "name": d.get("name"), "args": d.get("arguments"), "seq": e.get("seq", 0)})
            cur["calls"] += 1
        elif t == "tool/result":
            m = d.get("message") or {}
            cur["msgs"].append({"kind": "result", "text": text_of(m.get("content")), "seq": e.get("seq", 0)})
        elif t == "turn/end":
            cur["end"] = (d.get("reason") or {}).get("kind")
    return [turns[k] for k in sorted(turns)]


def to_messages(turn, max_tool_chars):
    msgs = [{"role": "user", "content": turn["user"].strip()}]
    for m in sorted(turn["msgs"], key=lambda x: x["seq"]):
        if m["kind"] == "assistant":
            txt = (m.get("text") or "").strip()
            if txt:
                msgs.append({"role": "assistant", "content": txt})
        elif m["kind"] == "call":
            try:
                payload = json.dumps({"name": m["name"], "arguments": json.loads(m["args"]) if isinstance(m["args"], str) else m["args"]}, ensure_ascii=False)
            except Exception:
                payload = json.dumps({"name": m["name"], "arguments": m["args"]}, ensure_ascii=False)
            block = f"<tool_call>\n{payload}\n</tool_call>"
            if msgs and msgs[-1]["role"] == "assistant":
                msgs[-1]["content"] += "\n\n" + block
            else:
                msgs.append({"role": "assistant", "content": block})
        elif m["kind"] == "result":
            txt = (m.get("text") or "").strip()
            if len(txt) > max_tool_chars:
                txt = txt[:max_tool_chars] + "…[truncated]"
            msgs.append({"role": "tool", "content": txt})
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--max-steps", type=int, default=14, help="正向样本步数上限")
    ap.add_argument("--min-steps", type=int, default=1)
    ap.add_argument("--max-tool-chars", type=int, default=1200)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    pats = a.files or [os.path.basename(p)[:-6] for p in sorted(glob.glob(os.path.join(AUDIT, "s*.jsonl")))]
    pos, neg, skipped = [], [], 0

    for name in pats:
        path = os.path.join(AUDIT, f"{name}.jsonl")
        if not os.path.isfile(path):
            print(f"[skip] {name}: 无文件")
            continue
        events = load_events(path)
        turns = build_turns(events)
        sp, sn = 0, 0
        for tr in turns:
            if not tr["user"] or tr["calls"] == 0:
                skipped += 1
                continue
            msgs = to_messages(tr, a.max_tool_chars)
            if not any(m["role"] == "assistant" for m in msgs):
                skipped += 1
                continue
            kitty_hits = len(KITTY_RE.findall(json.dumps(msgs, ensure_ascii=False)))
            meta = {"cat": "real-trajectory", "src": name, "steps": tr["calls"], "outcome": tr["end"], "kittyCalls": kitty_hits}
            row = {"messages": msgs, "meta": meta}
            good = (tr["end"] == "completed" and a.min_steps <= tr["calls"] <= a.max_steps)
            if good:
                pos.append(row); sp += 1
            else:
                neg.append(row); sn += 1
        print(f"[{name}] turns={len(turns)} pos={sp} neg={sn}")

    print(f"\n[sum] pos={len(pos)} neg={len(neg)} skipped(turn 无用户/无调用)={skipped}")
    if pos:
        steps = [p["meta"]["steps"] for p in pos]
        print(f"[pos] steps min={min(steps)} max={max(steps)} avg={sum(steps)/len(steps):.1f}")
    if a.dry_run:
        print("[dry-run] 未落盘")
        return

    os.makedirs(DATA, exist_ok=True)
    for fn, rows in (("real_sft.jsonl", pos), ("real_neg.jsonl", neg)):
        with open(os.path.join(DATA, fn), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[ok] → {DATA}\\real_sft.jsonl / real_neg.jsonl")


if __name__ == "__main__":
    main()
