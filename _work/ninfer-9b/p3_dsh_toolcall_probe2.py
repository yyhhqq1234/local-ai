# p3_dsh_toolcall_probe2.py — 判定 9B 是否具备「结构化 tool_calls」能力（DSH agent loop 前提）
# 三组对照：①训练格式 system（kitty 语料原文）②强约束 JSON 调用 ③OpenAI tools + 明确要求发起调用
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
                       "properties": {"path": {"type": "string"}, "limit": {"type": "number"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "kitty_ce", "description": "KittyCE 通道执行内存指令",
        "parameters": {"type": "object",
                       "properties": {"op": {"type": "string"}},
                       "required": ["op"]}}},
]

CASES = [
    ("T1-trained-format", "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。",
     "目标进程 kitty-target.exe 已 OPEN，帮我读一下模块基址处的 dword。", False),
    ("T2-json-only", "你是执行层。只输出一个 JSON 对象，形如 {\"name\":\"read\",\"arguments\":{\"path\":\"...\",\"limit\":20}}，不要任何解释文字。",
     "读取 README.md 前 20 行。", True),
    ("T3-openai-tools", "你是石井，本地工作区执行层。必须调用工具，不要凭记忆编造文件内容。",
     "读取 README.md 前 20 行，然后告诉我第一行是什么。", True),
]


def post(payload, timeout=120):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    c.request("POST", "/v1/chat/completions", body=json.dumps(payload).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, raw


def main():
    for name, sys_text, user_text, with_tools in CASES:
        p = {"model": MODEL, "temperature": 0, "max_tokens": 160,
             "chat_template_kwargs": {"enable_thinking": False},
             "messages": [{"role": "system", "content": sys_text},
                          {"role": "user", "content": user_text}]}
        if with_tools:
            p["tools"] = TOOLS
            p["tool_choice"] = "auto"
        t0 = time.time()
        st, raw = post(p)
        dt = time.time() - t0
        d = json.loads(raw)
        msg = (d.get("choices") or [{}])[0].get("message", {})
        fin = (d.get("choices") or [{}])[0].get("finish_reason")
        print("==", name, "status", st, "%.2fs" % dt, "finish", fin,
              "prompt_tok", (d.get("usage") or {}).get("prompt_tokens"))
        print(json.dumps({"content": msg.get("content"),
                          "tool_calls": msg.get("tool_calls")},
                         ensure_ascii=False, indent=2)[:1200])
        print()


if __name__ == "__main__":
    main()
