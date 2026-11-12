# p3_spec_bench.py — 投机解码 A/B：基线 vs 0.6B 草稿模型
import json
import os
import statistics
import subprocess
import time
import http.client

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
BIN = os.path.join(BASE, "engines", "llama-cpp", "llama-bin", "llama-server.exe")
MODEL = os.path.join(BASE, "models", "9b", "gguf", "kittyrev9b-Q5_K_M-im.gguf")
DRAFT = os.path.join(BASE, "models", "9b", "draft", "Qwen3.5-0.8B-MoE-A0.6B-Q4_K_M.gguf")
PORT = 8097
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."

COMMON = ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "1024", "--jinja", "--no-warmup",
          "-fa", "on", "--parallel", "1"]

SETS = [
    ("no-draft", COMMON),
    ("draft8", COMMON + ["-md", DRAFT, "--spec-draft-n-max", "8", "--spec-draft-n-min", "2",
                         "--spec-draft-p-min", "0.6", "--spec-draft-ngl", "99"]),
    ("draft4", COMMON + ["-md", DRAFT, "--spec-draft-n-max", "4", "--spec-draft-n-min", "1",
                         "--spec-draft-p-min", "0.5", "--spec-draft-ngl", "99"]),
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
            t.get("predicted_per_second") or 0)


def run(name, flags):
    log = open(os.path.join(BASE, "engines", "llama-cpp", "spec.log"), "ab")
    p = subprocess.Popen([BIN, "-m", MODEL] + flags + ["--host", "127.0.0.1", "--port", str(PORT)],
                         stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(180):
            time.sleep(1)
            if p.poll() is not None:
                return {"set": name, "error": "died rc=%s" % p.poll()}
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
                c.request("GET", "/health"); r = c.getresponse(); r.read(); c.close()
                if r.status == 200:
                    ready = True; break
            except Exception:
                pass
        if not ready:
            return {"set": name, "error": "not ready"}
        chat("warmup", 8)
        sp = []
        text = ""
        for _ in range(4):
            text, s = chat(FIXED, 256)
            sp.append(s)
        return {"set": name, "decode_median": round(statistics.median(sp), 2),
                "decode_all": [round(x, 1) for x in sp], "head": text[:60].replace("\n", " ")}
    finally:
        try:
            p.terminate(); p.wait(timeout=25)
        except Exception:
            try: p.kill()
            except Exception: pass
        log.close(); time.sleep(2)


for name, flags in SETS:
    print(json.dumps(run(name, flags), ensure_ascii=False), flush=True)

