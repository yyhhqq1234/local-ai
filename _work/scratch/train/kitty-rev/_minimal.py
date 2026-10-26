import json, urllib.request
BASE = "http://127.0.0.1:1234"
with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
    mid = json.loads(r.read())["data"][0]["id"]

tests = ["你好", "你好，请用一句话介绍你自己", "1+1 等于几", "输出 Hello"]
for u in tests:
    body = {"model": mid, "messages": [{"role": "user", "content": u}],
            "max_tokens": 64, "temperature": 0.7}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        ch = d["choices"][0]
        msg = ch["message"]
        print("=" * 60)
        print(f"user: {u}")
        print(f"  finish_reason = {ch.get('finish_reason')}")
        print(f"  content({len(msg.get('content') or '')}) = {repr((msg.get('content') or '')[:200])}")
        print(f"  usage = {d.get('usage')}")
    except Exception as e:
        print(f"user: {u}  -> {type(e).__name__}: {e}")
