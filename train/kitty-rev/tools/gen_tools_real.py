#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_tools_real.py — 从 kitty-toolbox 源码解析**真实**参数 schema

为什么需要：
  tool-manifest.ts 的 `actions` 字段是「机器可读动作面」描述，
  **不是**真实的参数名。例如 kitty_ce 的 actions 是 ['op','batch']，
  真实参数却是 `op: string` / `ops: string[]`，根本没有 `action` 这个键。
  第一版 tools.json 把 action 当成所有工具的必填项 → 模型学会了填
  kitty_ce{"action":"op"} 这种不存在的调用，op-syntax 判据全灭。

真实 schema 在 src/tools/*.ts 的 defineTool({ inputs: {...} }) 里，
形态是自定义描述对象：{ type, required?, description?, items?, enum? }。

输出（覆盖）data/intent3/v6-mix/tools.json
"""
import json
import os
import re
import sys

SRC_DIR = r"D:\DrCE(26.2.16)\kitty-toolbox\src"      # 递归；工具定义分布在 src/*.ts 与 src/tools/*.ts 两处
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "intent3", "v6-mix", "tools.json")


def read_all():
    chunks = []
    for root, _dirs, files in os.walk(SRC_DIR):
        if "node_modules" in root:
            continue
        for fn in sorted(files):
            if not fn.endswith(".ts"):
                continue
            if fn in ("tool-manifest.ts",):     # 这是清单不是定义（无 parameters，会污染解析）
                continue
            p = os.path.join(root, fn)
            chunks.append((os.path.relpath(p, SRC_DIR), open(p, encoding="utf-8", errors="replace").read()))
    return chunks


def match_brace(s, i):
    """s[i] == '{'，返回配对 '}' 的下标（跳过字符串）"""
    depth = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c in ("'", '"', "`"):
            q = c
            i += 1
            while i < n:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == q:
                    break
                i += 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def parse_inputs(body):
    """解析 inputs 体：key: { type: '...', required?: true, description: '...' }"""
    props = {}
    required = []
    i, n = 0, len(body)
    key_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*\{")
    while i < n:
        m = key_re.search(body, i)
        if not m:
            break
        key = body[m.start():m.start() + m.end()].split(":")[0].strip()
        bstart = body.index("{", m.start())
        bend = match_brace(body, bstart)
        if bend < 0:
            break
        inner = body[bstart + 1:bend]

        def grab(field):
            mm = re.search(field + r"\s*:\s*'([^']*)'", inner)
            return mm.group(1) if mm else None

        typ = grab("type") or "string"
        desc = grab("description") or ""
        is_req = bool(re.search(r"required\s*:\s*true", inner))
        enum = None
        em = re.search(r"enum\s*:\s*\[([^\]]*)\]", inner)
        if em:
            enum = [x.strip().strip("'\"") for x in em.group(1).split(",") if x.strip()]

        p = {"type": typ}
        if desc:
            p["description"] = desc[:200]
        if enum:
            p["enum"] = enum
        if typ == "array":
            p["items"] = {"type": "string"}
        if typ == "number" or typ == "integer":
            p["type"] = "number"
        props[key] = p
        if is_req:
            required.append(key)
        i = bend + 1
    return props, required


def load_manifest_meta():
    """tool-manifest.ts 是 channel/actions/description 的权威来源（它没有 parameters，
    read_all 会跳过它，所以这里单独读一次补元数据）。"""
    p = os.path.join(SRC_DIR, "tool-manifest.ts")
    if not os.path.exists(p):
        return {}
    text = open(p, encoding="utf-8", errors="replace").read()
    pat = re.compile(
        r"\{\s*name:\s*'([^']+)'\s*,\s*channel:\s*'([^']+)'\s*,\s*actions:\s*\[([^\]]*)\]\s*,"
        r"(?:\s*ops:\s*\[([^\]]*)\]\s*,)?\s*description:\s*'([^']*)'", re.S)

    def names(s):
        return [x.strip().strip("'\"") for x in s.split(",") if x.strip()]

    meta = {}
    for m in pat.finditer(text):
        meta[m.group(1)] = {
            "channel": m.group(2),
            "actions": names(m.group(3)),
            "ops": names(m.group(4)) if m.group(4) else [],
            "description": m.group(5),
        }
    return meta


def main():
    tools = {}
    for fn, text in read_all():
        for m in re.finditer(r"name:\s*'(kitty_[a-z0-9_]+|reverse_[a-z0-9_]+)'", text):
            name = m.group(1)
            seg = text[m.end():m.end() + 8000]
            # defineTool({ name, description, parameters: {...}, output, execute })
            im = re.search(r"\bparameters\s*:\s*\{", seg)
            if not im:
                cand = {"params": {}, "required": [], "src": fn}
            else:
                bstart = seg.index("{", im.start())
                bend = match_brace(seg, bstart)
                body = seg[bstart + 1:bend] if bend > 0 else ""
                props, req = parse_inputs(body)
                cand = {"params": props, "required": req, "src": fn}
            # 同名多处定义时，保留参数更全的那份（避免被 grep 命中的无参定义先占位）
            prev = tools.get(name)
            if prev is None or (not prev["params"] and cand["params"]):
                tools[name] = cand

        # 动态注册的一族：alias('kitty_rea_trace', 'trace_feature', 'desc', { 参数 }, [keys])
        for am in re.finditer(r"alias\(\s*'(kitty_[a-z0-9_]+)'\s*,\s*'[^']*'\s*,\s*'[^']*'\s*,\s*\{", text):
            name = am.group(1)
            bstart = text.index("{", am.end() - 1)
            bend = match_brace(text, bstart)
            body = text[bstart + 1:bend] if bend > 0 else ""
            props, _r = parse_inputs(body)
            props = {"args": {"type": "string",
                              "description": "上游参数（JSON 串或对象）"}, **props}
            cand = {"params": props, "required": [], "src": fn}
            prev = tools.get(name)
            if prev is None or (not prev["params"] and cand["params"]):
                tools[name] = cand

    # 读旧文件保留 channel/actions/description（供判据用）
    old = {}
    if os.path.exists(OUT):
        o = json.load(open(OUT, encoding="utf-8"))
        for t in o.get("tools", []):
            old[t["name"]] = t

    merged, schemas = [], []
    meta = load_manifest_meta()
    print(f"manifest 元数据 {len(meta)} 条（channel/actions/description）")
    for name, info in sorted(tools.items()):
        m = meta.get(name) or old.get(name, {})
        entry = {
            "name": name,
            "channel": m.get("channel", ""),
            "actions": m.get("actions", []),
            "ops": m.get("ops", []),
            "description": m.get("description", ""),
            "params": info["params"],
            "required": info["required"],
            "src": info["src"],
        }
        merged.append(entry)
        sch = {"type": "function", "function": {
            "name": name,
            "description": entry["description"] or name,
            "parameters": {
                "type": "object",
                "properties": entry["params"] or {"_": {"type": "string"}},
                "required": entry["required"],
            }}}
        schemas.append(sch)

    out = {"generated_from": SRC_DIR, "count": len(merged),
           "tools": merged, "function_schemas": schemas}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"解析工具 {len(merged)} 个 → {OUT}")
    print(f"有必填参数的 {sum(1 for t in merged if t['required'])} 个")
    print("\n关键工具的真实参数（对照第一版错在哪）：")
    for nm in ("kitty_ce", "kitty_ops", "kitty_status", "kitty_patch", "kitty_jadx",
               "kitty_rea_trace", "kitty_x64dbg", "kitty_km"):
        t = tools.get(nm)
        if not t:
            print(f"  {nm:<18} MISSING")
            continue
        ps = ", ".join(f"{k}{'*' if k in t['required'] else ''}:{v.get('type')}"
                       for k, v in t["params"].items()) or "(无参数)"
        print(f"  {nm:<18} {ps}")
    print("\n（* = required）")


if __name__ == "__main__":
    main()
