#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_deep_27b.py — 深度缺陷修复（在 clean_27b_data / fix_27b_leaks 之上）

对应 deep_audit_27b.py 查出的病灶，逐条处置：

  F1  正文伪 tool_call 文本 → 结构化
        assistant content 里的 `<tool_call>{...}</tool_call>` 解析成真正的
        assistant.tool_calls（name/arguments/id），文本块剥离。
        JSON 不合法 → 只剥离文本块；剥离后正文为空 → 丢行。
        理由：现状是「教模型在正文里手打 tool_call 文本」，这是 tool_call 幻觉的
        直接病灶（模型学的是文本形态，不是结构形态，且从未见过 schema）。

  F2  孤儿 tool 消息 → 补配对或剔除
        tool 消息前没有带 tool_calls 的 assistant 时：
          能从最近 assistant 文本解析出 `kitty_x action=y` → 合成 tool_calls 配对
          解析不到 → 丢弃该 tool 消息（保留其后的 assistant 内容）

  F3  tools=null → 逐行最小 schema
        只给「本行实际提到的 kitty_* 工具」最多 3 个，parameters 用
        {type:object, additionalProperties:true, properties:{action}}，控制 token
        （ctx 只有 2048，塞全量 schema 会吃掉答案预算）。

  F4  无 system 行 → 补默认 system（kitty 类补 kitty system；其它补中性 system）

  F5  模板霸屏 → 同 cat 同答案封顶
        kitty 类（tool-route/kb-re/op-syntax/kb-tool/real-trajectory/空 cat）
        同答案最多留 --cap 份；门控类（scene/cont/multi/style/expand/glossary）
        不设限（单一拒绝句式是设计，必须保留）。

  F6  残留：TODO/FIXME/待补 → 丢行；零宽/控制符/FFFD → 清洗；占位/XXX/C:\\Users
        属技术术语或示例路径 → 保留（不误杀）

  F7  自重复：8-gram 重复率 > --rep-drop 且长度 >200 → 丢行

  F8  元话术开头（作为/抱歉/我无法…）→ 丢行

  F9  近重复 user（SimHash64 汉明≤3）→ 保留信息量更大的一条（答案更长者）

用法：
    python fix_deep_27b.py --data <in.jsonl> --out <out.jsonl> [--cap 3] [--dry]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys

KITTY_RE = re.compile(r"\bkitty_[a-z0-9_]+")
# <tool_call> 块：允许里面是多行 JSON
TC_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
# 残留 <tool_call> 标记（无闭合）
TC_LOOSE_RE = re.compile(r"</?tool_call>")
ACT_RE = re.compile(r"\b(kitty_[a-z0-9_]+)\s+(?:action=|op=)?([A-Za-z0-9_]+)?")
CTRL_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
BAD_MARK_RE = re.compile(r"\b(TODO|FIXME|待补|TBD)\b")
META_OPEN = ("作为", "抱歉", "我无法", "对不起", "我理解", "以下是我", "根据你的要求")

GATE_CATS = {"scene", "cont", "multi", "style", "expand", "glossary"}
KITTY_SYS = ("你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。"
             "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，"
             "按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。")
GEN_SYS = "你是本地工作区的执行层。直接给结果，不解释过程。"


def ans_of(msgs):
    return "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant").strip()


def rep8(text: str) -> float:
    s = re.sub(r"\s+", "", text)
    if len(s) < 40:
        return 0.0
    g = [s[i:i + 8] for i in range(len(s) - 7)]
    return 1.0 - len(set(g)) / len(g)


def simhash(text: str) -> int:
    s = re.sub(r"\s+", "", text)
    if not s:
        return 0
    g = [s[i:i + 3] for i in range(max(0, len(s) - 2))] or [s]
    v = [0] * 64
    for x in g:
        h = int.from_bytes(hashlib.blake2b(x.encode(), digest_size=8).digest(), "big")
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if v[b] > 0:
            out |= 1 << b
    return out


def make_tool_schema(names, cats_gate=False):
    """逐行最小 tools schema（只含本行实际用到的工具，控 token）

    parameters 用 additionalProperties=true 的开放对象：目的是让模型见到
    「这批工具存在、参数是对象」，而不是记住某个固定 schema。
    """
    out = []
    for nm in names:
        desc = (f"kitty 逆向工作台工具 {nm}（参数面见 action/op 取值）"
                if nm.startswith("kitty_") else f"本地执行工具 {nm}")
        props = {"action": {"type": "string"}, "op": {"type": "string"}}
        if not nm.startswith("kitty_"):
            props = {"command": {"type": "string"}, "path": {"type": "string"}}
        out.append({
            "type": "function",
            "function": {
                "name": nm,
                "description": desc,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "additionalProperties": True,
                },
            },
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cap", type=int, default=3, help="kitty 类同答案封顶份数")
    ap.add_argument("--rep-drop", type=float, default=0.5, help="8-gram 重复率超过则丢行")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    st = collections.Counter()
    before = collections.Counter()
    kept = []
    chain_cap = collections.defaultdict(collections.Counter)  # cat -> anshash -> n
    sim_buckets = collections.defaultdict(list)
    cat_out = collections.Counter()

    with open(a.data, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            msgs = row.get("messages") or []
            cat = (row.get("meta") or {}).get("cat") or ""
            before[cat or "<none>"] += 1
            st["in"] += 1

            # ---------- 清洗控制字符 ----------
            blob_raw = json.dumps(msgs, ensure_ascii=False)
            if CTRL_RE.search(blob_raw) or "\ufffd" in blob_raw:
                st["f6_ctrl_cleaned"] += 1
                for m in msgs:
                    if isinstance(m.get("content"), str):
                        m["content"] = CTRL_RE.sub("", m["content"])
                        m["content"] = m["content"].replace("\ufffd", "")

            # ---------- F6 残留标记 ----------
            full = json.dumps(msgs, ensure_ascii=False)
            if BAD_MARK_RE.search(full):
                st["f6_bad_mark_dropped"] += 1
                continue

            # ---------- F1 伪 tool_call 文本 → 结构化 ----------
            tcid = 0
            converted = 0
            for m in msgs:
                if m.get("role") != "assistant":
                    continue
                c = m.get("content")
                if not isinstance(c, str) or "<tool_call>" not in c:
                    continue
                blocks = TC_BLOCK_RE.findall(c)
                rest = TC_BLOCK_RE.sub("", c)
                new_tcs = []
                for b in blocks:
                    try:
                        obj = json.loads(b)
                    except Exception:
                        st["f1_json_bad"] += 1
                        continue
                    name = obj.get("name") or ""
                    args = obj.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {"raw": args}
                    if not name:
                        st["f1_json_bad"] += 1
                        continue
                    tcid += 1
                    new_tcs.append({
                        "id": f"call_{st['in']}_{tcid}",
                        "type": "function",
                        "function": {"name": name, "arguments": args or {}},
                    })
                if new_tcs:
                    m["tool_calls"] = (m.get("tool_calls") or []) + new_tcs
                    converted += len(new_tcs)
                m["content"] = TC_LOOSE_RE.sub("", rest).strip()
                if not m["content"] and not m.get("tool_calls"):
                    m["_empty_after_strip"] = True
            if converted:
                st["f1_toolcall_converted"] += converted
                st["f1_rows_converted"] += 1

            # 剥离后既无正文也无 tool_call 的 assistant → 丢掉整条（对话塌了）
            if any(m.pop("_empty_after_strip", False) for m in msgs):
                st["f1_rows_dropped_empty"] += 1
                continue

            # ---------- F2 孤儿 tool ----------
            fixed = []
            for i, m in enumerate(msgs):
                if m.get("role") == "tool":
                    prev = fixed[-1] if fixed else None
                    if not (prev and prev.get("role") == "assistant" and prev.get("tool_calls")):
                        # 从更早的 assistant 文本里找工具名 + action 配对
                        synth = None
                        for back in reversed(fixed):
                            if back.get("role") != "assistant":
                                continue
                            txt = back.get("content") or ""
                            mm = KITTY_RE.search(txt)
                            if mm:
                                am = re.search(r"action=([A-Za-z0-9_]+)", txt)
                                args = {"action": am.group(1)} if am else {}
                                synth = {
                                    "id": f"call_{st['in']}_orphan",
                                    "type": "function",
                                    "function": {"name": mm.group(0), "arguments": args},
                                }
                            break
                        if synth:
                            prev["tool_calls"] = (prev.get("tool_calls") or []) + [synth]
                            st["f2_orphan_paired"] += 1
                        else:
                            st["f2_orphan_dropped"] += 1
                            continue
                fixed.append(m)
            msgs = fixed

            # ---------- F4 补 system ----------
            if not msgs or msgs[0].get("role") != "system":
                st["f4_system_added"] += 1
                sys_txt = GEN_SYS if cat in ("", "general") else KITTY_SYS
                msgs = [{"role": "system", "content": sys_txt}] + msgs

            # ---------- F7 自重复 ----------
            A = ans_of(msgs)
            if len(A) > 200 and rep8(A) > a.rep_drop:
                st["f7_self_repeat_dropped"] += 1
                continue

            # ---------- F8 元话术 ----------
            if A.startswith(META_OPEN):
                st["f8_meta_open_dropped"] += 1
                continue

            # ---------- F9 近重复（user 与 answer 都近似才算重复） ----------
            U = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
            hu, ha = simhash(U), simhash(A)
            dup_of = -1
            if U.strip() and A.strip():
                for b in range(4):
                    key = (b, (hu >> (b * 16)) & 0xFFFF)
                    for (hu2, ha2, idx) in sim_buckets.get(key, ()):
                        # 只丢「问法近似 + 答案近似」的对（问法近似但答案不同 = 不同标签，必须留）
                        if bin(hu ^ hu2).count("1") <= 3 and bin(ha ^ ha2).count("1") <= 6:
                            dup_of = idx
                            break
                    if dup_of >= 0:
                        break
            if dup_of >= 0:
                st["f9_near_dup_dropped"] += 1
                continue
            if U.strip():
                for b in range(4):
                    sim_buckets[(b, (hu >> (b * 16)) & 0xFFFF)].append((hu, ha, len(kept)))

            # ---------- F5 模板封顶（kitty 类才限） ----------
            if cat not in GATE_CATS:
                ah = hashlib.blake2b(A.encode(), digest_size=8).hexdigest()
                chain_cap[cat][ah] += 1
                if chain_cap[cat][ah] > a.cap:
                    st["f5_template_capped"] += 1
                    continue

            # ---------- F3 tools ----------
            # 优先取 tool_calls 里真的用到的函数名（含非 kitty 工具如 pwsh），
            # 再用正文提到的 kitty_* 补位；总数封顶 3 个（ctx 2048，schema 要省 token）
            cntn = collections.Counter()
            for m in msgs:
                for tc in (m.get("tool_calls") or []):
                    nm = ((tc.get("function") or {}).get("name") or "").strip()
                    if nm:
                        cntn[nm] += 5          # 实际调用权重高
            for nm in KITTY_RE.findall(json.dumps(msgs, ensure_ascii=False)):
                cntn[nm] += 1
            names = [nm for nm, _ in cntn.most_common(3)]
            row["tools"] = make_tool_schema(names) if names else None
            if row["tools"]:
                st["f3_tools_attached"] += 1
                for nm in names:
                    if not nm.startswith("kitty_"):
                        st[f"f3_nonkitty_{nm}"] += 1
            else:
                st["f3_tools_null"] += 1

            row["messages"] = msgs
            if not row.get("meta"):
                row["meta"] = {"cat": cat}
            kept.append(row)
            cat_out[cat or "<none>"] += 1
            st["out"] += 1

    print("[stat]")
    for k in sorted(st):
        print(f"  {k:26s} {st[k]}")
    print("[per-cat]")
    for c, n in cat_out.most_common():
        print(f"  {c:18s} {before.get(c,0):6d} → {n:6d}")

    if a.dry:
        print("[dry] 未写盘")
        return 0

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()
    with open(a.out + ".sha256", "w", encoding="utf-8", newline="\n") as f:
        f.write(sha + "\n")
    sz = os.path.getsize(a.out) / (1 << 20)
    print(f"[out] {a.out}  {len(kept)} 行  {sz:.1f} MiB  sha256 {sha[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
