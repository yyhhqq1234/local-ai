# p3_shim_raw.py — 看引擎对「<tool_call> 协议」的原始回包：原生 tool_calls 还是正文？
import json, sys, http.client

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
MODEL = "kittyrev-oxcoder9b-nsfw-gate-full-GSQ"

PROTO = """## 工具调用协议（本机 9B 专用，必须遵守）
要调用工具时，正文里只输出一行（不要用 ``` 包裹，不要附加解释）：
<tool_call>{"name":"工具名","arguments":{"参数":"值"}}</tool_call>
arguments 必须是合法 JSON 且键名照工具 schema；kitty_* 用 {"op":"..."} 这种形态。
一次只发一个调用；等工具结果回来再决定下一步。不需要工具时正常回答，不要输出该标记。
可用工具：read / ops_bash / kitty_ce"""

TOOLS = [
    {"type": "function", "function": {"name": "read", "description": "读取文本文件的指定行区间",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "number"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "kitty_ce", "description": "KittyCE 通道执行内存指令",
     "parameters": {"type": "object", "properties": {"op": {"type": "string"}}, "required": ["op"]}}},
]

CASES = [
    ("tool", "读取 README.md 的前 20 行，然后告诉我第一行是什么。"),
    ("plain", "用一句话说明本地推理最大的好处。"),
]


def run(user, with_tools=True):
    p = {"model": MODEL, "max_tokens": 120, "temperature": 0, "stream": True,
         "stream_options": {"include_usage": True},
         "chat_template_kwargs": {"enable_thinking": False},
         "messages": [{"role": "system", "content": "你是石井，本地工作区执行层。" + "\n\n" + PROTO},
                      {"role": "user", "content": user}]}
    if with_tools:
        p["tools"] = TOOLS
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
    c.request("POST", "/v1/chat/completions", body=json.dumps(p).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    print("HTTP", r.status)
    kinds = []
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
            kinds.append(("tool_calls", json.dumps(dl["tool_calls"], ensure_ascii=False)[:300]))
        if dl.get("content"):
            kinds.append(("content", dl["content"][:200]))
        if ch.get("finish_reason"):
            kinds.append(("finish", ch["finish_reason"]))
        if o.get("usage"):
            kinds.append(("usage", json.dumps(o["usage"])))
    c.close()
    for k, v in kinds[:40]:
        print(" ", k, "|", v)


for name, user in CASES:
    print("\n===", name, "===")
    run(user)
