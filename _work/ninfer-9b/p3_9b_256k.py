"""9B：把 KV 放主机内存（--no-kv-offload），上下文拉到 256k。

用法：python p3_9b_256k.py <ctx> [kv_dtype q8_0|f16]
输出：JSON（启动 ok / 显存余 / 各长度 prompt 的 prefill、TTFT）
"""
import json
import os
import subprocess
import sys
import time
import http.client

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
BIN = os.path.join(BASE, "engines", "llama-cpp", "llama-bin", "llama-server.exe")
MODEL = os.path.join(BASE, "models", "9b", "gguf", "kittyrev9b-Q5_K_M-im.gguf")
PORT = 8080
SMI = r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_540239129807163b\nvidia-smi.exe"
UNIT = "本地推理把模型放在用户机器上运行，数据不出域，延迟低，成本可控。"


def free_mb():
    out = subprocess.run([SMI, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return int(out.splitlines()[0]) if out else -1


def chat(prompt, n=16, timeout=3600):
    body = {"model": "x", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); raw = r.read(); c.close()
    return r.status, json.loads(raw or b"{}"), raw


def make(n_tokens):
    return "以下是工程笔记，请用一句话总结：\n" + UNIT * max(1, n_tokens // 20)


def main():
    ctx = int(sys.argv[1]) if len(sys.argv) > 1 else 262144
    kv = sys.argv[2] if len(sys.argv) > 2 else "q8_0"
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    time.sleep(3)
    argv = [BIN, "-m", MODEL, "-ngl", "99", "-c", str(ctx), "--no-kv-offload",
            "--cache-type-k", kv, "--cache-type-v", kv,
            "-b", "2048", "-ub", "1024", "-fa", "on", "--jinja", "--no-warmup",
            "--parallel", "1", "--host", "127.0.0.1", "--port", str(PORT)]
    log = os.path.join(BASE, "engines", "llama-cpp", "llama-256k.log")
    fh = open(log, "ab")
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT)
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
    print(json.dumps({"stage": "start", "ctx": ctx, "kv": kv, "ready": ready,
                      "free_vram_mb": free_mb()}, ensure_ascii=False), flush=True)
    if not ready:
        with open(log, encoding="utf-8", errors="ignore") as f:
            print("\n".join(f.read().splitlines()[-6:]))
        return
    for target in (8000, 32000, 65536, 131072, 200000):
        if target > ctx - 128:
            continue
        t0 = time.time()
        st, d, raw = chat(make(target))
        dt = time.time() - t0
        t = d.get("timings") or {}
        print(json.dumps({"target": target, "status": st,
                          "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"),
                          "prefill_tok_s": round(t.get("prompt_per_second") or 0, 1),
                          "ttft_s": round((t.get("prompt_ms") or 0) / 1000, 2),
                          "wall_s": round(dt, 1), "free_vram_mb": free_mb(),
                          "err": None if st == 200 else raw.decode("utf-8", "replace")[:120]},
                         ensure_ascii=False), flush=True)


main()
