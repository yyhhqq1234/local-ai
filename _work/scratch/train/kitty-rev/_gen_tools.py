# -*- coding: utf-8 -*-
"""从 kitty-toolbox/src/tool-manifest.ts（只读）解析 64 工具的 name/actions/description → tools schema"""
import json, re, os

SRC = r"D:\DrCE(26.2.16)\kitty-toolbox\src\tool-manifest.ts"
raw = open(SRC, encoding="utf-8").read()

# 逐条抓 { name: 'x', channel: 'y', actions: [...], ops?: [...], description: '...' }
pat = re.compile(
    r"\{\s*name:\s*'([^']+)'\s*,\s*channel:\s*'([^']+)'\s*,\s*actions:\s*\[([^\]]*)\]\s*,"
    r"(?:\s*ops:\s*\[([^\]]*)\]\s*,)?\s*description:\s*'([^']*)'",
    re.S)

def names(s):
    return [x.strip().strip("'\"") for x in s.split(",") if x.strip()]

tools, seen = [], set()
for m in pat.finditer(raw):
    name, channel, acts, ops, desc = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if name in seen: continue
    seen.add(name)
    actions = names(acts)
    tools.append({
        "name": name, "channel": channel,
        "actions": actions, "ops": names(ops) if ops else [],
        "description": desc,
    })

print("解析到工具数:", len(tools))
assert len(tools) >= 60, f"只解析到 {len(tools)} 个，低于预期 60"

# 生成 OpenAI function schema
def schema_of(t):
    props = {"action": {"type": "string", "enum": t["actions"],
                        "description": "动作面（取其一）"}}
    # 常见参数按通道补（够用于教"选哪个工具 + 哪个 action"）
    ch = t["channel"]
    if ch in ("static", "rea-mcp", "ida-mcp"):
        props["target"] = {"type": "string", "description": "目标文件/样本路径"}
        props["out"] = {"type": "string", "description": "产物输出目录"}
    if ch.startswith("A") or ch in ("runtime", "kernel", "orch"):
        props["addr"] = {"type": "string", "description": "目标地址 0x…"}
        props["pid"] = {"type": "integer", "description": "目标进程 pid"}
    return {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": {
                "type": "object",
                "properties": props,
                "required": ["action"],
            },
        },
    }

os.makedirs("data/intent3/v6-mix", exist_ok=True)
out = {"generated_from": SRC, "count": len(tools), "tools": tools,
       "function_schemas": [schema_of(t) for t in tools]}
with open("data/intent3/v6-mix/tools.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

print("写出 data/intent3/v6-mix/tools.json")
print("\n通道分布:")
import collections
for c, n in collections.Counter(t["channel"] for t in tools).most_common():
    print(f"  {c:<16} {n}")
print("\n判分器关心的三个工具:")
for nm in ("kitty_jadx", "kitty_rea_trace", "kitty_ops"):
    t = next((x for x in tools if x["name"] == nm), None)
    print(f"  {nm:<18} actions={t['actions'] if t else 'MISSING'}")
print("\n算力线专项（六条主线要用到的）:")
for nm in ("kitty_status","kitty_ce","kitty_x64dbg","kitty_patch","kitty_die","kitty_ghidra",
           "kitty_sym","kitty_km","kitty_dualview","kitty_variants","kitty_selftest","kitty_pchain"):
    t = next((x for x in tools if x["name"] == nm), None)
    print(f"  {nm:<18} {t['actions'] if t else 'MISSING'}")
