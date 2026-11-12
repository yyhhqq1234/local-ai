# p3_ctx_matrix.py — 定位「工具调用失效」的变量：长 system 还是工具数量？
# 4 格：system 短/长 × 工具 3/14，同一 user 任务，看是否产出 tool_calls
import json, http.client, sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
MODEL = "kittyrev-oxcoder9b-nsfw-gate-full-GSQ"
USER = "读取 README.md 前 20 行。"

SHORT_SYS = """## 工具调用协议（本机 9B 专用，必须遵守）
需要工具时，整个回复只输出这一行，一字不改：
<tool_call>{"name":"工具名","arguments":{"参数":"值"}}</tool_call>
禁止输出裸 JSON、禁止 ``` 包裹、禁止解释；一次只发一个调用。
禁止凭记忆编造文件内容或内存数值——没有工具结果就不要写这类内容。
可用工具：read / ops_bash / kitty_ce"""

RULES = "\n\n".join("## 约定段 %d\n本段是工作区运行约定，用于说明交付形态与推进规则。" % i for i in range(1, 41))
SKILLS = "<available_skills>\n" + "\n".join(
    "- `skill-%d`: 这是第 %d 个技能的说明行，用于占位与体积模拟。" % (i, i) for i in range(120)) + "\n</available_skills>"
LONG_SYS = "\n\n".join([RULES, SKILLS, SHORT_SYS])

BASE = [
    ("read", {"path": {"type": "string"}, "limit": {"type": "number"}}, ["path"]),
    ("ops_bash", {"command": {"type": "string"}, "description": {"type": "string"}}, ["command", "description"]),
    ("kitty_ce", {"op": {"type": "string"}}, []),
]
EXTRA = [
    ("write", {"file_path": {"type": "string"}, "content": {"type": "string"}}, ["file_path", "content"]),
    ("edit", {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, ["file_path"]),
    ("ops_glob", {"pattern": {"type": "string"}}, ["pattern"]),
    ("ops_grep", {"pattern": {"type": "string"}}, ["pattern"]),
    ("skill", {"name": {"type": "string"}}, ["name"]),
    ("web_search", {"queries": {"type": "array", "items": {"type": "string"}}}, ["queries"]),
    ("ninfer_status", {"action": {"type": "string"}}, []),
    ("ninfer_engine", {"action": {"type": "string"}}, []),
    ("kitty_ops", {"filter": {"type": "string"}}, []),
    ("kitty_settings", {"action": {"type": "string"}}, ["action"]),
    ("kitty_status", {"probe": {"type": "boolean"}}, []),
]


def tools(defs):
    return [{"type": "function", "function": {"name": n, "description": n + " 工具",
             "parameters": {"type": "object", "properties": p, "required": r}}} for n, p, r in defs]


def run(label, sys_text, tdefs):
    body = {"model": MODEL, "max_tokens": 160, "temperature": 0, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": USER}],
            "tools": tools(tdefs), "tool_choice": "auto"}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=300)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read()
    c.close()
    d = json.loads(raw)
    msg = (d.get("choices") or [{}])[0].get("message", {})
    tc = msg.get("tool_calls") or []
    txt = (msg.get("content") or "").replace("\n", " ")[:110]
    print("%-28s status=%s sysChars=%-6d tools=%-2d calls=%-2d %s | %s" % (
        label, r.status, len(sys_text), len(tdefs), len(tc),
        json.dumps(tc, ensure_ascii=False)[:140], txt))
    return len(tc)


ok = 0
ok += run("A short-sys + 3 tools", SHORT_SYS, BASE) > 0
ok += run("B short-sys + 14 tools", SHORT_SYS, BASE + EXTRA) > 0
ok += run("C long-sys + 3 tools", LONG_SYS, BASE) > 0
ok += run("D long-sys + 14 tools", LONG_SYS, BASE + EXTRA) > 0
print("\ntool-call cells: %d/4" % ok)
