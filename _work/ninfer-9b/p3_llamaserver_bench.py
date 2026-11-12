import json
import os
import re
import statistics
import subprocess
import sys
import time
import http.client

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
BIN = os.path.join(BASE, "llama-bin", "llama-server.exe")
GG = os.path.join(BASE, "gguf")
PORT = 18123
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."

MODELS = sys.argv[1:] or [
    "kittyrev9b-Q5_K_M-im.gguf",
    "kittyrev9b-Q4_K_M-im.gguf",
    "kittyrev9b-Q6_K.gguf",
    "kittyrev9b-Q5_K_M.gguf",
]


def post(path, body, t=900):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=t)
    c.request("POST", path, body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


def run_one(model):
    mpath = os.path.join(GG, model)
    if not os.path.isfile(mpath):
        return {"model": model, "error": "model missing"}
    log = open(os.path.join(BASE, "llamaserver.log"), "ab")
    argv = [BIN, "-m", mpath, "-ngl", "99", "-c", "4096", "--host", "127.0.0.1",
            "--port", str(PORT), "--no-warmup"]
    try:
        p = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
    except Exception as e:
        log.write(("POPEN_FAIL %s %r\n" % (e, argv)).encode())
        log.close()
        return {"model": model, "error": "popen: %s" % e}
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
        if not ready:
            return {"model": model, "error": "server not ready (rc=%s)" % p.poll()}
        post("/v1/chat/completions", {"model": "x", "max_tokens": 8, "temperature": 0,
                                      "messages": [{"role": "user", "content": "warmup"}]})
        speeds, garbled = [], 0
        for _ in range(4):
            d = post("/v1/chat/completions", {"model": "x", "max_tokens": 256, "temperature": 0,
                                              "messages": [{"role": "user", "content": FIXED}]})
            t = d.get("timings") or {}
            speeds.append(t.get("predicted_per_second") or 0)
            txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if "\ufffd" in txt or re.search(r"(.)\1{6,}", txt):
                garbled += 1
        return {"model": model, "decode_median": round(statistics.median(speeds), 2),
                "min": round(min(speeds), 2), "max": round(max(speeds), 2),
                "all": [round(x, 1) for x in speeds], "garbled": garbled}
    finally:
        try:
            p.terminate(); p.wait(timeout=25)
        except Exception:
            try: p.kill()
            except Exception: pass
        log.close()
        time.sleep(3)


for m in MODELS:
    print(json.dumps(run_one(m), ensure_ascii=False), flush=True)
