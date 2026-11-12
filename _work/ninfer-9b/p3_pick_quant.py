# p3_pick_quant.py — 逐模型干净测量：先卸载其它模型，再 5 次速度 + 17 例回归
import json
import os
import re
import statistics
import subprocess
import time
import http.client

PORT = 11434
OLLAMA = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."
MODELS = ["kittyrev9b-q4km", "kittyrev9b-q5km", "kittyrev9b-q6k"]

SETS = [
    ("p1-2+2", "What is 2+2?", 32, "4"),
    ("p2-hello", "Say hello in Chinese.", 24, "你好"),
    ("p3-gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
    ("p4-pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
    ("p5-unittest", "List 3 benefits of unit testing.", 128, "test"),
]
GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def post(path, body, t=900):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=t)
    c.request("POST", path, body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


def gen(model, prompt, n, system=None):
    if system:
        d = post("/api/chat", {"model": model, "stream": False,
                               "options": {"num_predict": n, "temperature": 0, "num_ctx": 4096},
                               "messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": prompt}]})
        text = (d.get("message") or {}).get("content") or ""
    else:
        d = post("/api/generate", {"model": model, "prompt": prompt, "stream": False,
                                   "options": {"num_predict": n, "temperature": 0, "num_ctx": 4096}})
        text = d.get("response") or ""
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
    for other in MODELS:
        if other != m:
            subprocess.run([OLLAMA, "stop", other], capture_output=True)
    time.sleep(2)
    gen(m, "warmup", 8)  # 预热/装载
    speeds = []
    for _ in range(5):
        _, s = gen(m, FIXED, 256)
        speeds.append(s)
    ok = 0; total = 0; marks = []
    for name, p, n, kw in SETS:
        for _ in range(3):
            t, _ = gen(m, p, n); total += 1
            b = bad(t)
            if b: marks.append(name + ":" + b)
            elif kw.lower() in t.lower(): ok += 1
    t, _ = gen(m, "What is 2+2?", 16, system="You are a helpful assistant."); total += 1
    if bad(t) == "" and "4" in t: ok += 1
    print(json.dumps({"model": m,
                      "speed_median": round(statistics.median(speeds), 2),
                      "speed_min": round(min(speeds), 2),
                      "speed_max": round(max(speeds), 2),
                      "speed_all": [round(x, 1) for x in speeds],
                      "quality": f"{ok}/{total}", "bad": marks}, ensure_ascii=False))
