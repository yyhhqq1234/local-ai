# p3_llama_tune.py — llama.cpp 9B 参数 A/B（质量不变的前提下找最快组合）
import json
import os
import statistics
import subprocess
import time
import http.client

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
BIN = os.path.join(BASE, "engines", "llama-cpp", "llama-bin", "llama-server.exe")
MODEL = os.path.join(BASE, "models", "9b", "gguf", "kittyrev9b-Q5_K_M-im.gguf")
PORT = 8095
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."

SETS = [
    ("A baseline", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup"]),
    ("B +fa on", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup", "-fa", "on"]),
    ("C +fa+kv8", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup",
                   "-fa", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]),
    ("D +fa+par1", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup",
                    "-fa", "on", "--parallel", "1"]),
    ("E +fa+ub256", ["-ngl", "99", "-c", "8192", "-b", "1024", "-ub", "256", "--jinja", "--no-warmup", "-fa", "on"]),
    ("F +fa+mlock", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup",
                     "-fa", "on", "--no-mmap", "--mlock"]),
]


def chat(prompt, n):
    body = {"model": "x", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=600)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    t = d.get("timings") or {}
    return (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "",
            t.get("predicted_per_second") or 0, t.get("prompt_per_second") or 0)


def run(name, flags):
    log = open(os.path.join(BASE, "engines", "llama-cpp", "tune.log"), "ab")
    t0 = time.time()
    p = subprocess.Popen([BIN, "-m", MODEL] + flags + ["--host", "127.0.0.1", "--port", str(PORT)],
                         stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(180):
            time.sleep(1)
            if p.poll() is not None:
                break
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
                c.request("GET", "/health"); r = c.getresponse(); r.read(); c.close()
                if r.status == 200:
                    ready = True; break
            except Exception:
                pass
        load_s = round(time.time() - t0, 1)
        if not ready:
            return {"set": name, "error": "not ready (rc=%s)" % p.poll()}
        chat("warmup", 8)
        sp, pp = [], []
        for _ in range(4):
            _, s, q = chat(FIXED, 256)
            sp.append(s); pp.append(q)
        return {"set": name, "decode_median": round(statistics.median(sp), 2),
                "decode_all": [round(x, 1) for x in sp],
                "prefill_median": round(statistics.median(pp), 1), "load_s": load_s}
    finally:
        try:
            p.terminate(); p.wait(timeout=20)
        except Exception:
            try: p.kill()
            except Exception: pass
        log.close(); time.sleep(2)


for name, flags in SETS:
    print(json.dumps(run(name, flags), ensure_ascii=False), flush=True)
