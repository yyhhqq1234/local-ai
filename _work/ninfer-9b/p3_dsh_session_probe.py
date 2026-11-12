# p3_dsh_session_probe.py — 任务1：按 DSH 真实请求形态（system + tools）打 9B 引擎
# 口径：附着到已在跑的引擎（默认 127.0.0.1:1234，由 DSH 适配器 build-9b 拉起），不 spawn、不 kill。
# 判据：① content 非空且不乱码 ② 无 500/503 ③ TTFT 记录（历史 164 ms）④ decode tok/s 记录
import json
import re
import sys
import time
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
OUT = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\p3-dsh-session-result.json"

# 适配器 build-9b 的 compactSystemText（lib/index.js:147）
COMPACT_SYS = "你是石井，本地工作区执行层。中文、简短、直接；先给结论后给理由。"

# 504-token 级别 system（p3_long_system.py 同源 + DSH 风格执行纪律）
LONG_SYS = (
    ("You are a careful local assistant. Follow the operator's instructions exactly, "
     "keep answers short, and never invent tool results. ") * 20
    + "\n## 执行纪律\n1) 工具缺失即上报。2) 写文件后最多回读 1 次。"
      "3) 结论优先，不要前置评估。4) 收口一行：当前/结果/下一步。\n"
)

def fn(name, desc, props, req):
    return {"type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": {"type": "object", "properties": props, "required": req}}}

TOOLS = [
    fn("read", "读取文本文件的指定行区间",
       {"path": {"type": "string", "description": "相对工作区路径"},
        "offset": {"type": "number"}, "limit": {"type": "number"}}, ["path"]),
    fn("write", "写入或覆盖一个文本文件",
       {"file_path": {"type": "string"}, "content": {"type": "string"}}, ["file_path", "content"]),
    fn("edit", "按字面量替换文件中的一段文本",
       {"file_path": {"type": "string"}, "old_string": {"type": "string"},
        "new_string": {"type": "string"}}, ["file_path", "old_string", "new_string"]),
    fn("ops_bash", "执行一条 bash 命令", {"command": {"type": "string"},
        "description": {"type": "string"}}, ["command", "description"]),
    fn("ops_glob", "按 glob 查找文件", {"pattern": {"type": "string"}}, ["pattern"]),
    fn("ops_grep", "按正则搜索文件内容", {"pattern": {"type": "string"},
        "path": {"type": "string"}}, ["pattern"]),
    fn("skill", "加载一个技能的完整说明", {"name": {"type": "string"}}, ["name"]),
    fn("web_search", "联网检索（1-4 条查询）", {"queries": {"type": "array",
        "items": {"type": "string"}}}, ["queries"]),
    fn("ninfer_status", "查看本地引擎状态", {"action": {"type": "string"}}, []),
    fn("ninfer_engine", "启停本地引擎", {"action": {"type": "string"},
        "profile": {"type": "string"}}, ["action"]),
    fn("ninfer_model", "模型列表/切换", {"action": {"type": "string"},
        "file": {"type": "string"}}, ["action"]),
    fn("ninfer_params", "读写引擎关键参数", {"action": {"type": "string"}}, ["action"]),
    fn("kitty_ce", "KittyCE 通道执行内存指令", {"op": {"type": "string"},
        "ops": {"type": "array", "items": {"type": "string"}}}, []),
    fn("kitty_ops", "查询 CE 通道 OP 表", {"filter": {"type": "string"}}, []),
    fn("kitty_settings", "逆向会话真相源/任务状态机", {"action": {"type": "string"},
        "target": {"type": "string"}}, ["action"]),
    fn("kitty_status", "通道健康检查", {"probe": {"type": "boolean"}}, []),
]

CASES = [
    ("A-compact-sys+tools", COMPACT_SYS,
     "用一句话说明 read 工具干什么，然后给出一次 read 调用的 JSON 参数。", 256, True),
    ("B-long-sys+tools", LONG_SYS,
     "用一句话说明 ops_bash 工具干什么，然后给出一次调用它的 JSON 参数。", 256, True),
    ("C-decode-speed", COMPACT_SYS,
     "用中文写一段约 150 字的说明，讲本地推理的三个好处。", 200, False),
]

GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def looks_garbled(text):
    if not text.strip():
        return True, "empty"
    if "\ufffd" in text:
        return True, "replacement-char"
    m = GARBAGE.search(text)
    if m:
        s = m.group(0)
        if any(c.islower() for c in s) and any(c.isupper() for c in s):
            return True, "base64-like:" + s[:24]
    # 乱码常见形态：同一字符连续 >6 次
    if re.search(r"(.)\1{6,}", text):
        return True, "char-repeat"
    return False, ""


def stream_chat(messages, tools, max_tokens):
    payload = {
        "model": "kittyrev-oxcoder9b-nsfw-gate-full-GSQ",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"
    body = json.dumps(payload).encode()
    t0 = time.time()
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=300)
    conn.request("POST", "/v1/chat/completions", body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    status = resp.status
    if status != 200:
        err = resp.read().decode("utf-8", "replace")[:400]
        conn.close()
        return {"status": status, "error": err}
    content, reasoning, usage, ttft, ttft_reason = [], [], None, None, None
    tool_calls = {}
    first_tok = last_tok = None
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            break
        try:
            obj = json.loads(data)
        except Exception:
            continue
        if obj.get("usage"):
            usage = obj["usage"]
        for ch in obj.get("choices", []):
            d = ch.get("delta") or {}
            if d.get("reasoning_content"):
                if ttft_reason is None:
                    ttft_reason = time.time() - t0
                reasoning.append(d["reasoning_content"])
            if d.get("content"):
                now = time.time()
                if ttft is None:
                    ttft = now - t0
                    first_tok = now
                last_tok = now
                content.append(d["content"])
            for tc in d.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(idx, {"name": "", "args": ""})
                if tc.get("function", {}).get("name"):
                    slot["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"):
                    slot["args"] += tc["function"]["arguments"]
    conn.close()
    total = time.time() - t0
    text = "".join(content)
    ct = (usage or {}).get("completion_tokens") or 0
    pt = (usage or {}).get("prompt_tokens") or 0
    dec = None
    if ct > 1 and first_tok and last_tok and last_tok > first_tok:
        dec = (ct - 1) / (last_tok - first_tok)
    return {"status": status, "content": text, "reasoning_chars": len("".join(reasoning)),
            "reasoning_head": "".join(reasoning)[:120], "tool_calls": list(tool_calls.values()),
            "prompt_tokens": pt, "completion_tokens": ct,
            "ttft_s": ttft, "ttft_reasoning_s": ttft_reason, "total_s": total,
            "decode_tok_s": dec}


def main():
    out = {"port": PORT, "cases": []}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)
    c.request("GET", "/v1/models")
    models = json.loads(c.getresponse().read())
    c.close()
    out["models"] = models
    for name, sys_text, user_text, mt, use_tools in CASES:
        msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": user_text}]
        r = stream_chat(msgs, use_tools, mt)
        bad = looks_garbled(r.get("content", "")) if r.get("status") == 200 else (True, "http-%s" % r["status"])
        rec = {"case": name, "use_tools": use_tools, "ok": r.get("status") == 200 and not bad[0],
               "garbled": bad[0], "garbled_reason": bad[1]}
        rec.update({k: v for k, v in r.items() if k not in ("content",)})
        rec["content_head"] = (r.get("content") or "")[:400]
        out["cases"].append(rec)
        print(json.dumps(rec, ensure_ascii=False, indent=2))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
