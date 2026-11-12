#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""norm_dataset.py —— 把 SFT 数据集规整成单一 schema（供 HF datasets 直接 cast）

问题（2026-11-01 实测）：gen3_1p 的顶层键组合有 7 种（id/meta/_aug/_coverage/contrast/tools 各自缺缺有有），
datasets.load_dataset("json") 按首批样本推断 schema 后 cast 失败：
    CastError: Couldn't cast  messages: list<item: string>  meta: string
                _aug: struct<...>  tools: list<struct<...>>  ...
训练在 "Generating train split" 阶段就崩，GPU 全程 0 MiB。

处理：只保留训练真正用到的两个字段，且每行都带上、类型统一
    {"messages": [{"role","content",("tool_calls")}], "tools": [...] 或 null}

train_kitty.py 的 to_text() 用 ex["messages"] 与 ex.get("tools")（falsy 即跳过），
所以 tools=null 与缺键等价，规范成 null 最省事。

用法：
  python norm_dataset.py --src <in.jsonl> --out <out.jsonl>
"""
import argparse
import json
import hashlib
import os
import sys


def norm_tools(tools):
    """统一 tools 结构；非法项丢弃。保持 LLM 习惯的 {type, function} 包装。"""
    if not tools:
        return None
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if isinstance(t.get("function"), dict) else t
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        params = fn.get("parameters")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = None
        if not isinstance(params, dict):
            params = {"type": "object", "properties": {}, "required": []}
        params.setdefault("type", "object")
        if not isinstance(params.get("properties"), dict):
            props = params.get("properties")
            try:
                params["properties"] = json.loads(props) if isinstance(props, str) else {}
            except Exception:
                params["properties"] = {}
        if not isinstance(params.get("required"), list):
            params["required"] = []
        out.append({"type": "function",
                    "function": {"name": fn["name"],
                                 "description": fn.get("description") or "",
                                 "parameters": params}})
    return out or None


def norm_messages(msgs):
    out = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role") or m.get("from")
        if role not in ("system", "user", "assistant", "tool"):
            continue
        c = m.get("content")
        if isinstance(c, (list, dict)):
            c = json.dumps(c, ensure_ascii=False)
        c = "" if c is None else str(c)
        nm = {"role": role, "content": c}
        tcs = m.get("tool_calls")
        if isinstance(tcs, list) and tcs:
            fixed = []
            for tc in tcs:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                # 训练脚本自己会把 str 解析成 dict；这里保持原样即可
                fixed.append({"id": tc.get("id") or "",
                              "type": "function",
                              "function": {"name": fn.get("name") or "",
                                           "arguments": args if isinstance(args, str)
                                           else json.dumps(args or {}, ensure_ascii=False)}})
            if fixed:
                nm["tool_calls"] = fixed
        out.append(nm)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    n_in = n_out = 0
    n_tools = 0
    n_bad = 0
    with open(a.src, encoding="utf-8") as fi, \
         open(a.out, "w", encoding="utf-8", newline="\n") as fo:
        for line in fi:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                d = json.loads(line)
            except Exception:
                n_bad += 1
                continue
            msgs = norm_messages(d.get("messages") or d.get("conversations"))
            if len(msgs) < 2:
                n_bad += 1
                continue
            # meta 只保留 cat（train_kitty.py 的类别审计读 meta.cat；缺了会 FATAL）
            _m = d.get("meta") or {}
            cat = (_m.get("cat") if isinstance(_m, dict) else None) or ""
            row = {"messages": msgs,
                   "tools": norm_tools(d.get("tools")),
                   "meta": {"cat": str(cat)}}
            if row["tools"]:
                n_tools += 1
            fo.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_out += 1

    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
    open(a.out + ".sha256", "w").write(h + "\n")
    print(f"[in ] {n_in} 行")
    print(f"[out] {n_out} 行（含 tools {n_tools}），丢弃 {n_bad}")
    print(f"[sha] {h[:16]}  {os.path.getsize(a.out)/1048576:.1f} MiB")
    print(f"→ {a.out}")


if __name__ == "__main__":
    sys.exit(main())
