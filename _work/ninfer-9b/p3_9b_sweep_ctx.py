"""9B 速度+长上下文折中扫描：设备 KV 下不同 ctx / KV 类型 / ub，测 prefill、decode、长文质量。

每个配置：启动 → 短 prompt decode → 32k/64k prefill+TTFT → 32k 针尖测试（质量）→ 显存
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
    d = json.loads(raw or b"{}")
    return r.status, d


def build(n_tokens):
    return "以下是工程笔记，请用一句话总结：\n" + UNIT * max(1, n_tokens // 20)


def needle(prefix_tokens, code):
    filler = UNIT * max(1, prefix_tokens // 20)
    return ("请阅读下面的长文档，最后回答问题。\n" + filler +
            "\n\n【关键记录】本次运行的验证码是 %s。\n\n" % code + filler +
            "\n\n问题：文档里的验证码是多少？只回答验证码本身。")


def run_cfg(name, ctx, kvk, kvv, ub, nb, host_kv_offload=False):
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    time.sleep(3)
    argv = [BIN, "-m", MODEL, "-ngl", "99", "-c", str(ctx),
            "--cache-type-k", kvk, "--cache-type-v", kvv,
            "-b", str(nb), "-ub", str(ub), "-fa", "on", "--jinja", "--no-warmup",
            "--parallel", "1", "--host", "127.0.0.1", "--port", str(PORT)]
    if host_kv_offload:
        argv.append("--no-kv-offload")
    log = os.path.join(BASE, "engines", "llama-cpp", "sweep.log")
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
    if not ready:
        return {"cfg": name, "ready": False}
    res = {"cfg": name, "ctx": ctx, "kv": kvk + "/" + kvv, "ub": ub, "b": nb,
           "host_kv": host_kv_offload, "ready": True, "free_vram_mb": free_mb()}
    st, d = chat("Explain why local inference is useful. Give a detailed answer.", 256)
    res["decode_short"] = round((d.get("timings") or {}).get("predicted_per_second") or 0, 1)
    for target in (32768, 65536):
        if target > ctx - 1024:
            continue
        st, d = chat(build(target), 8)
        t = d.get("timings") or {}
        res["p%d_prefill" % (target // 1024)] = round(t.get("prompt_per_second") or 0, 1)
        res["p%d_ttft_s" % (target // 1024)] = round((t.get("prompt_ms") or 0) / 1000, 1)
        res["p%d_tokens" % (target // 1024)] = (d.get("usage") or {}).get("prompt_tokens")
    # 质量：32k 针尖
    code = "K7Q2M9"
    st, d = chat(needle(30000, code), 32)
    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    res["needle32k_ok"] = code in txt
    res["needle32k_head"] = txt[:40].replace("\n", " ")
    res["free_vram_after_mb"] = free_mb()
    return res


CFGS = [
    ("dev-q8-256k-ub256", 262144, "q8_0", "q8_0", 256, 512, False),
    ("dev-q8q4-256k-ub512", 262144, "q8_0", "q4_0", 512, 1024, False),
    ("dev-q8-128k-ub512", 131072, "q8_0", "q8_0", 512, 1024, False),
    ("host-q8-256k-ub1024", 262144, "q8_0", "q8_0", 1024, 2048, True),
]

for cfg in CFGS:
    print(json.dumps(run_cfg(*cfg), ensure_ascii=False), flush=True)
