# p3_quant_compare.py — Q4_K_M / Q5_K_M / Q6_K 三档：速度（256 tok × 3）+ 17 例质量回归
import json
import re
import statistics
import http.client

PORT = 11434
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."
MODELS = ["kittyrev9b-q4km", "kittyrev9b-q5km", "kittyrev9b-q6k"]

SETS = [
    ("2+2", "What is 2+2?", 32, "4"),
    ("hello", "Say hello in Chinese.", 24, "你好"),
    ("gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
    ("pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
    ("unittest", "List 3 benefits of unit testing.", 128, "test"),
]
GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def gen(model, prompt, n, system=None, stream=False):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=900)
    if system:
        body = {"model": model, "stream": False,
                "options": {"num_predict": n, "temperature": 0, "num_ctx": 4096},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        path = "/api/chat"
    else:
        body = {"model": model, "prompt": prompt, "stream": False,
                "options": {"num_predict": n, "temperature": 0, "num_ctx": 4096}}
        path = "/api/generate"
    c.request("POST", path, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    text = d.get("response") or (d.get("message") or {}).get("content") or ""
    ec, ed = d.get("eval_count") or 0, d.get("eval_duration") or 1
    return text, ec / (ed / 1e9)


def bad(t):
    if not t.strip():
        return "empty"
    if "\ufffd" in t:
        return "replacement-char"
    m = GARBAGE.search(t)
    if m and any(ch.islower() for ch in m.group(0)) and any(ch.isupper() for ch in m.group(0)):
        return "base64-like"
    if re.search(r"(.)\1{6,}", t):
        return "char-repeat"
    return ""


for m in MODELS:
    speeds = []
    for _ in range(3):
        _, s = gen(m, FIXED, 256)
        speeds.append(s)
    ok = 0
    total = 0
    marks = []
    for name, p, n, kw in SETS:
        for _ in range(3):
            t, _ = gen(m, p, n)
            total += 1
            b = bad(t)
            if b:
                marks.append(name + ":" + b)
            elif kw is None or kw.lower() in t.lower():
                ok += 1
    t, _ = gen(m, "What is 2+2?", 16, system="You are a helpful assistant.")
    total += 1
    if bad(t) == "" and "4" in t:
        ok += 1
    print(json.dumps({"model": m,
                      "speed_median": round(statistics.median(speeds), 2),
                      "speed_min": round(min(speeds), 2),
                      "speed_max": round(max(speeds), 2),
                      "ok": ok, "total": total, "bad": marks},
                     ensure_ascii=False))
