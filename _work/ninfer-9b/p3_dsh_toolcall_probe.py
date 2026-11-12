# p3_dsh_toolcall_probe.py — 任务1 补测：结构化 tool_calls 是否真的产出（DSH agent loop 的前提）
# 口径：非流式 + 流式各一次，要求模型必须发起工具调用；同时读 usage 里的前缀复用字段。
import json
import sys
import time
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
MODEL = "kittyrev-oxcoder9b-nsfw-gate-full-GSQ"

TOOLS = [
    {"type": "function", "function": {
        "name": "read", "description": "读取文本文件的指定行区间",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "offset": {"type": "number"},
                                      "limit": {"type": "number"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "ops_bash", "description": "执行一条 bash 命令",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}, "description": {"type": "string"}},
                       "required": ["command", "description"]}}},
]

SYS = "你是石井，本地工作区执行层。中文、简短、直接。需要读文件时必须调用 read 工具，不要凭记忆编造文件内容。"
USER = "读取 README.md 的前 20 行，然后告诉我第一行是什么。"


def post(payload, timeout=120):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    c.request("POST", "/v1/chat/completions", body=json.dumps(payload).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, raw


def main():
    base = {"model": MODEL, "temperature": 0, "max_tokens": 128,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": USER}],
            "tools": TOOLS, "tool_choice": "auto"}
    t0 = time.time()
    st, raw = post(dict(base))
    dt = time.time() - t0
    print("== non-stream status", st, "%.2fs" % dt)
    d = json.loads(raw)
    msg = (d.get("choices") or [{}])[0].get("message", {})
    print(json.dumps({"content": msg.get("content"),
                      "tool_calls": msg.get("tool_calls"),
                      "usage": d.get("usage"),
                      "engine": {k: d.get(k) for k in
                                 ("prefix_cache_hit_tokens", "prefix_reuse_path", "timings_seconds") if k in d}},
                     ensure_ascii=False, indent=2))

    # 流式：看 tool_call_delta 是否按 index 下发
    p = dict(base, stream=True)
    t0 = time.time()
    st, raw = post(p)
    text = raw.decode("utf-8", "replace")
    print("\n== stream status", st, "%.2fs" % (time.time() - t0))
    tcs = {}
    content = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        for ch in obj.get("choices", []):
            dl = ch.get("delta") or {}
            if dl.get("content"):
                content.append(dl["content"])
            for tc in dl.get("tool_calls") or []:
                i = tc.get("index", 0)
                s = tcs.setdefault(i, {"name": "", "args": ""})
                if (tc.get("function") or {}).get("name"):
                    s["name"] = tc["function"]["name"]
                if (tc.get("function") or {}).get("arguments"):
                    s["args"] += tc["function"]["arguments"]
    print(json.dumps({"content": "".join(content)[:200], "tool_calls": tcs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
