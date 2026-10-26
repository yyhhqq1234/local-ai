# -*- coding: utf-8 -*-
"""in-domain 12 题：带训练时的 system prompt + tools，逐条问，记录 tool_calls 与 content"""
import json, sys, urllib.request, time

TAG = sys.argv[1]
rows = json.load(open("data/_indomain12.json", encoding="utf-8"))

# 从训练集取 system prompt（in-domain 必须带上）
src = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
first = json.loads(open(src, encoding="utf-8").readline())
SYS = next((m.get("content") or "") for m in first["messages"] if m.get("role") == "system")
print(f"[{TAG}] system len={len(SYS)}  samples={len(rows)}")

BASE = "http://127.0.0.1:1234"
with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
    MID = json.loads(r.read())["data"][0]["id"]
print(f"[{TAG}] model={MID}")

res = []
t0 = time.time()
for i, r in enumerate(rows, 1):
    body = {"model": MID,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": r["user"]}],
            "max_tokens": 1024, "temperature": 0.7,
            "tools": r["tools"]}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            d = json.loads(resp.read())
        ch = d["choices"][0]; m = ch.get("message") or {}
        tc = m.get("tool_calls") or []
        content = m.get("content") or ""
        calls = [{"name": c["function"]["name"], "args": c["function"]["arguments"][:200]} for c in tc]
        res.append({"i": i, "cat": r["cat"], "user": r["user"], "calls": calls,
                    "content": content, "finish": ch.get("finish_reason"),
                    "ntok": (d.get("usage") or {}).get("completion_tokens")})
        print(f"[{TAG}] [{i:>2}] {r['cat']:<18} calls={len(tc):<2} content={len(content):<5} "
              f"{calls[0]['name'] if calls else '-'}", flush=True)
    except Exception as e:
        res.append({"i": i, "cat": r["cat"], "user": r["user"], "err": str(e)})
        print(f"[{TAG}] [{i:>2}] ERR {e}", flush=True)

json.dump({"tag": TAG, "model": MID, "results": res},
          open(f"logs/v6/INDOMAIN-{TAG}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"[{TAG}] done in {time.time()-t0:.0f}s  → logs/v6/INDOMAIN-{TAG}.json")
