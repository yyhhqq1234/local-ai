import json, urllib.request
BASE = "http://127.0.0.1:1234"
with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
    mid = json.loads(r.read())["data"][0]["id"]

for mt in (256, 1024):
    u = "1+1 等于几"
    body = {"model": mid, "messages": [{"role": "user", "content": u}],
            "max_tokens": mt, "temperature": 0.7}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.loads(r.read())
        ch = d["choices"][0]; msg = ch["message"]
        det = (d.get("usage") or {}).get("completion_tokens_details") or {}
        c = msg.get("content") or ""
        rc = msg.get("reasoning_content") or ""
        print("=" * 60)
        print(f"max_tokens={mt}  finish={ch.get('finish_reason')}")
        print(f"  completion={d['usage']['completion_tokens']}  reasoning={det.get('reasoning_tokens')}")
        print(f"  content({len(c)}) = {repr(c[:300])}")
        print(f"  reasoning({len(rc)}) = {repr(rc[:300])}")
    except Exception as e:
        print(f"max_tokens={mt} -> {type(e).__name__}: {e}")
