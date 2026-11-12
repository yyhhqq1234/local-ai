# p3_ctx_matrix2.py — 复现 R2：compact system + 协议 + user 尾提醒 + 14 工具，非流式 vs 流式
import json, http.client

PORT = 1234
MODEL = "kittyrev-oxcoder9b-nsfw-gate-full-GSQ"
COMPACT = "你是石井，本地工作区执行层。中文、简短、直接；先给结论后给理由。"
PROTO = """## 工具调用协议（本机 9B 专用，必须遵守）
需要工具时，整个回复只输出这一行，一字不改：
<tool_call>{"name":"工具名","arguments":{"参数":"值"}}</tool_call>
禁止输出裸 JSON、禁止 ``` 包裹、禁止解释；一次只发一个调用。
禁止凭记忆编造文件内容或内存数值——没有工具结果就不要写这类内容。
arguments 必须是合法 JSON，键名照工具 schema；kitty_* 用 {"op":"..."} 形态。
可用工具：read / write / edit / ops_bash / ops_glob / ops_grep / skill / web_search / ninfer_status / ninfer_engine / kitty_ce / kitty_ops / kitty_settings / kitty_status"""
REMIND = """

[工具协议] 需要文件内容 / 内存数值 / 命令输出时，必须先发一行
<tool_call>{"name":"工具名","arguments":{...}}</tool_call>
再依据结果回答；没有工具结果就不要写这类内容，禁止凭记忆编造。"""
USER = "读取 README.md 前 20 行。" + REMIND

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


def post(label, system, stream):
    body = {"model": MODEL, "max_tokens": 160, "temperature": 0, "stream": stream,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": USER}],
            "tools": TOOLS, "tool_choice": "auto"}
    if stream:
        body["stream_options"] = {"include_usage": True}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=300)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    calls, text, fin = [], "", None
    if not stream:
        d = json.loads(r.read())
        msg = (d.get("choices") or [{}])[0].get("message", {})
        calls = msg.get("tool_calls") or []
        text = msg.get("content") or ""
        fin = (d.get("choices") or [{}])[0].get("finish_reason")
        pt = (d.get("usage") or {}).get("prompt_tokens")
    else:
        for line in r:
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            d = line[5:].strip()
            if d == b"[DONE]":
                break
            try:
                o = json.loads(d)
            except Exception:
                continue
            ch = (o.get("choices") or [{}])[0]
            dl = ch.get("delta") or {}
            if dl.get("tool_calls"):
                calls.append(dl["tool_calls"])
            if dl.get("content"):
                text += dl["content"]
            if ch.get("finish_reason"):
                fin = ch["finish_reason"]
            if o.get("usage"):
                pt = o["usage"].get("prompt_tokens")
    c.close()
    print("%-34s stream=%-5s prompt=%-5s finish=%-10s calls=%d | %s" % (
        label, stream, pt, fin, len(calls), text.replace("\n", " ")[:100]))


post("compact+proto+reminder", COMPACT + "\n\n" + PROTO, False)
post("compact+proto+reminder", COMPACT + "\n\n" + PROTO, True)
post("compact+proto (no reminder)", COMPACT + "\n\n" + PROTO, False)
# 对照组：与矩阵 B 同形（短 system 只放协议，user 不带提醒）
post("proto-only system(B 形态)", PROTO, False)
