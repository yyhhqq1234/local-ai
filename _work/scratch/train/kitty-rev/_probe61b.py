# -*- coding: utf-8 -*-
import json, urllib.request, urllib.error

BASE = "http://127.0.0.1:1234"
# 正确 model id
with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
    mid = json.loads(r.read())["data"][0]["id"]
print("MODEL =", mid)

# 从 tools.json 取全量 schema
_tj = "data/intent3/v6-mix/tools.json"
tools = json.load(open(_tj, encoding="utf-8"))["function_schemas"]
print("TOOLS =", len(tools))

rows = [json.loads(l) for l in open("data/eval-key6.jsonl", encoding="utf-8") if l.strip()]

for idx in (0, 1, 2, 3):
    row = rows[idx]
    user = row["messages"][0]["content"]
    body = {"model": mid,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": 512, "temperature": 0.7,
            "tools": tools}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.loads(r.read())
        msg = d["choices"][0]["message"]
        tc = msg.get("tool_calls") or []
        content = (msg.get("content") or "")
        print("=" * 70)
        print(f"[key{idx+1}] {(row.get('meta') or {}).get('cat')}  user: {user[:70]}")
        print(f"  tool_calls = {len(tc)}")
        for c in tc:
            print(f"    -> {c['function']['name']}  args={c['function']['arguments'][:150]}")
        print(f"  content({len(content)}): {content[:500]}")
    except urllib.error.HTTPError as e:
        print(f"[key{idx+1}] HTTP {e.code}: {e.read()[:200]}")
    except Exception as e:
        print(f"[key{idx+1}] {type(e).__name__}: {e}")
