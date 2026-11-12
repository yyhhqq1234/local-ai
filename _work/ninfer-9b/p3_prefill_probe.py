# p3_prefill_probe.py — 长 prompt 下的 prefill 速度（DSH 真实场景 ~4k token）
import json
import os
import statistics
import subprocess
import time
import http.client

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
BIN = os.path.join(BASE, "engines", "llama-cpp", "llama-bin", "llama-server.exe")
MODEL = os.path.join(BASE, "models", "9b", "gguf", "kittyrev9b-Q5_K_M-im.gguf")
PORT = 8096

SETS = [
    ("fa+ub512", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "512", "--jinja", "--no-warmup", "-fa", "on"]),
    ("fa+ub1024", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "1024", "--jinja", "--no-warmup", "-fa", "on"]),
    ("fa+ub2048", ["-ngl", "99", "-c", "8192", "-b", "2048", "-ub", "2048", "--jinja", "--no-warmup", "-fa", "on"]),
]

LONG = ("以下是工程笔记，请阅读后总结要点：\n" + ("本地推理把模型放在用户机器上运行，数据不出域，延迟更低，成本可控。" * 200))


def one(flags):
    log = open(os.path.join(BASE, "engines", "llama-cpp", "tune.log"), "ab")
    p = subprocess.Popen([BIN, "-m", MODEL] + flags + ["--host", "127.0.0.1", "--port", str(PORT)],
                         stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(180):
            time.sleep(1)
            if p.poll() is not None:
                return None
            try:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3)
                c.request("GET", "/health"); r = c.getresponse(); r.read(); c.close()
                if r.status == 200:
                    break
            except Exception:
                pass
        else:
            return None
        body = {"model": "x", "messages": [{"role": "user", "content": LONG}],
                "max_tokens": 32, "temperature": 0, "stream": False}
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=900)
        c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse(); d = json.loads(r.read()); c.close()
        t = d.get("timings") or {}
        return {"prefill_tok_s": round(t.get("prompt_per_second") or 0, 1),
                "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"),
                "decode_tok_s": round(t.get("predicted_per_second") or 0, 1)}
    finally:
        try:
            p.terminate(); p.wait(timeout=20)
        except Exception:
            try: p.kill()
            except Exception: pass
        log.close(); time.sleep(2)


for name, flags in SETS:
    r = one(flags)
    print(json.dumps({"set": name, **(r or {"error": "failed"})}, ensure_ascii=False), flush=True)
