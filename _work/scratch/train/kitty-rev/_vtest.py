import base64, json, urllib.request, time

p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\logs\v6\_vtest.png"
b64 = base64.b64encode(open(p, "rb").read()).decode()
print("image b64 len =", len(b64))

BASE = "http://127.0.0.1:1234"
with urllib.request.urlopen(BASE + "/v1/models", timeout=10) as r:
    MID = json.loads(r.read())["data"][0]["id"]
print("model =", MID)

tests = [
    ("图里写的是什么数字？只回数字。", 256),
    ("这张图片里有什么？用一句话描述。", 256),
]
for q, mt in tests:
    body = {"model": MID,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": q},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
            ]}],
            "max_tokens": mt, "temperature": 0.2}
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            d = json.loads(resp.read())
        ch = d["choices"][0]; m = ch.get("message") or {}
        c = m.get("content") or ""; rc = m.get("reasoning_content") or ""
        u = d.get("usage") or {}
        print("=" * 66)
        print(f"Q: {q}")
        print(f"  finish={ch.get('finish_reason')}  toks={u.get('completion_tokens')}  {time.time()-t0:.0f}s")
        print(f"  content({len(c)}) = {c[:300]!r}")
        print(f"  reasoning({len(rc)}) = {rc[:200]!r}")
    except urllib.error.HTTPError as e:
        print("=" * 66)
        print(f"Q: {q}\n  HTTP {e.code}: {e.read()[:300]}")
    except Exception as e:
        print("=" * 66)
        print(f"Q: {q}\n  {type(e).__name__}: {e}")
