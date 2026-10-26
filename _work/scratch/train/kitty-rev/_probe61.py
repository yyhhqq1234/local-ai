# -*- coding: utf-8 -*-
"""直接问 V6.1 模型，看它返回什么（含 tool_calls 与否）"""
import json, urllib.request

BASE = "http://127.0.0.1:1234"
rows = [json.loads(l) for l in open("data/eval-key6.jsonl", encoding="utf-8") if l.strip()]
tools = (rows[0].get("tools") or [])
print(f"tools = {len(tools)} 个")

for idx in (0, 1, 2):
    row = rows[idx]
    user = row["messages"][0]["content"]
    body = {
        "model": "x",
        "messages": [{"role": "user", "content": user}],
        "max_tokens": 512,
        "temperature": 0.7,
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read())
        msg = d["choices"][0]["message"]
        tc = msg.get("tool_calls") or []
        content = msg.get("content") or ""
        print("=" * 70)
        print(f"[key{idx+1}] user: {user[:80]}")
        print(f"  tool_calls = {len(tc)}")
        for c in tc:
            print(f"    -> {c['function']['name']}({c['function']['arguments'][:120]})")
        print(f"  content({len(content)} chars): {content[:400]}")
    except Exception as e:
        print(f"[key{idx+1}] FAIL {type(e).__name__}: {e}")
