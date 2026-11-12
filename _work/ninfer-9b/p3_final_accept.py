# p3_final_accept.py — 交付验收：固定 prompt 256 token × 3 速度 + 17 例回归（llama-server, GPU）
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
MODEL = os.path.join(BASE, "gguf", "kittyrev9b-Q5_K_M-im.gguf")
PORT = 8080
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."


def http_json(path, body=None, t=900):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=t)
    if body is None:
        c.request("GET", path)
    else:
        c.request("POST", path, body=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


def chat(prompt, n, system=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    d = http_json("/v1/chat/completions",
                  {"model": "x", "messages": msgs, "max_tokens": n, "temperature": 0, "stream": False})
    t = d.get("timings") or {}
    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return txt, (t.get("predicted_per_second") or 0)


def main():
    log = open(os.path.join(BASE, "llama-server.log"), "ab")
    p = subprocess.Popen([BIN, "-m", MODEL, "-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512",
                          "--host", "127.0.0.1", "--port", str(PORT), "--jinja", "--no-warmup",
                          "--metrics"], stdout=log, stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(180):
            time.sleep(1)
            if p.poll() is not None:
                break
            try:
                http_json("/health", t=3); ready = True; break
            except Exception:
                pass
        if not ready:
            print(json.dumps({"error": "server not ready"})); return
        chat("warmup", 8)
        speeds, bad = [], 0
        for _ in range(3):
            txt, sp = chat(FIXED, 256)
            speeds.append(sp)
            if "\ufffd" in txt or re.search(r"(.)\1{6,}", txt):
                bad += 1
        # 17 例
        SETS = [("2+2", "What is 2+2?", 32, "4"),
                ("hello", "Say hello in Chinese.", 24, "你好"),
                ("gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
                ("pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
                ("unittest", "List 3 benefits of unit testing.", 128, "test")]
        ok = total = 0
        marks = []
        for name, pr, n, kw in SETS:
            for _ in range(3):
                txt, _ = chat(pr, n)
                total += 1
                g = ("\ufffd" in txt) or bool(re.search(r"(.)\1{6,}", txt))
                if g:
                    marks.append(name + ":garbled")
                elif kw.lower() in txt.lower():
                    ok += 1
        txt, _ = chat("What is 2+2?", 16, system="You are a helpful assistant.")
        total += 1
        if "4" in txt and "\ufffd" not in txt:
            ok += 1
        print(json.dumps({"model": os.path.basename(MODEL),
                          "speed_median": round(statistics.median(speeds), 2),
                          "speed_all": [round(x, 1) for x in speeds],
                          "garbled_fixed": bad,
                          "regress_ok": ok, "regress_total": total,
                          "marks": marks}, ensure_ascii=False))
    finally:
        try:
            p.terminate(); p.wait(timeout=25)
        except Exception:
            try: p.kill()
            except Exception: pass
        log.close()


main()

