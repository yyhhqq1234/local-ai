# p3_proto_ab.py — 同一任务/同 14 工具，只换协议措辞，看哪版能稳定触发 tool_calls
import json, http.client

PORT = 1234
MODEL = "kittyrev-oxcoder9b-nsfw-gate-full-GSQ"
USER = "读取 README.md 前 20 行。"

S_B = """## 工具调用协议（本机 9B 专用，必须遵守）
需要工具时，整个回复只输出这一行，一字不改：
<tool_call>{"name":"工具名","arguments":{"参数":"值"}}</tool_call>
禁止输出裸 JSON、禁止 ``` 包裹、禁止解释；一次只发一个调用。
可用工具：read / ops_bash / kitty_ce"""

S_M2 = S_B.replace("可用工具：read / ops_bash / kitty_ce",
                   "可用工具：read / write / edit / ops_bash / ops_glob / ops_grep / skill / web_search / ninfer_status / ninfer_engine / kitty_ce / kitty_ops / kitty_settings / kitty_status")

S_B46 = """## 9B 工具调用
需要工具时必须严格按这个格式，只输出一行，不要用 ``` 包裹，不要解释：
<tool_call>{"name":"read","arguments":{"path":"README.md","limit":20}}</tool_call>
一次只发一个调用；不需要工具时正常回答，不要输出该标记。
可用工具：read / ops_bash / kitty_ce"""

S_BARE = """工具格式：<tool_call>{"name":"工具名","arguments":{...}}</tool_call>"""

DEFS = [
    ("read", {"path": {"type": "string"}, "limit": {"type": "number"}}, ["path"]),
    ("write", {"file_path": {"type": "string"}, "content": {"type": "string"}}, ["file_path", "content"]),
    ("edit", {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, ["file_path"]),
    ("ops_bash", {"command": {"type": "string"}, "description": {"type": "string"}}, ["command", "description"]),
    ("ops_glob", {"pattern": {"type": "string"}}, ["pattern"]),
    ("ops_grep", {"pattern": {"type": "string"}}, ["pattern"]),
    ("skill", {"name": {"type": "string"}}, ["name"]),
    ("web_search", {"queries": {"type": "array", "items": {"type": "string"}}}, ["queries"]),
    ("ninfer_status", {"action": {"type": "string"}}, []),
    ("ninfer_engine", {"action": {"type": "string"}}, []),
    ("kitty_ce", {"op": {"type": "string"}}, []),
    ("kitty_ops", {"filter": {"type": "string"}}, []),
    ("kitty_settings", {"action": {"type": "string"}}, ["action"]),
    ("kitty_status", {"probe": {"type": "boolean"}}, []),
]
TOOLS = [{"type": "function", "function": {"name": n, "description": n + " 工具",
          "parameters": {"type": "object", "properties": p, "required": r}}} for n, p, r in DEFS]


def run(label, system):
    body = {"model": MODEL, "max_tokens": 160, "temperature": 0, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": USER}],
            "tools": TOOLS, "tool_choice": "auto"}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=300)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message", {})
    tc = msg.get("tool_calls") or []
    print("%-22s sysChars=%-4d prompt=%-5s calls=%d finish=%s | %s" % (
        label, len(system), (d.get("usage") or {}).get("prompt_tokens"), len(tc),
        ch.get("finish_reason"), (msg.get("content") or "").replace("\n", " ")[:80]))
    return len(tc)


n = 0
n += run("S_B(3 names)", S_B) > 0
n += run("S_M2(14 names)", S_M2) > 0
n += run("S_B46(explicit)", S_B46) > 0
n += run("S_BARE(minimal)", S_BARE) > 0
print("\nworking protocols: %d/4" % n)
