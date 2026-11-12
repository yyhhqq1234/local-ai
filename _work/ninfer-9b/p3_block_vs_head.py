# p3_block_vs_head.py — 决定性对齐：把引擎 decode 阶段 dump 的真实 ah(=MTP 层输入) 喂给新头，
# 比较引擎 out 与新头 out 的 cosine。≈1 → 实现一致，差距在 stem 构造/ids；<<1 → 前向不一致。
import importlib.util
import json
import os
import struct
import subprocess
import sys
import time
import http.client
import numpy as np
import torch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
BASE = os.path.join(ROOT, r"_work\ninfer-9b")
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-mtp2f-GSQ.ninfer")
DUMP = os.path.join(BASE, "p3-block-new.bin")
PORT = 18995
HEAD = os.path.join(BASE, "mtp-out", "mtp-tuned-dump.safetensors")

PS = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
      "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def kill_own():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].strip().lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", p[0].strip(), "/F"], capture_output=True)


def req(path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def run_dump():
    if os.path.exists(DUMP):
        os.remove(DUMP)
    kill_own(); time.sleep(0.5)
    env = dict(os.environ)
    env["NINFER_TRACE_MTP_BLOCK"] = DUMP
    env["NINFER_PREFILL_MAX_TOKENS"] = "64"
    fh = open(os.path.join(BASE, "p3-block-new.log"), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ready = False
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    ready = True; break
            except Exception:
                pass
        if not ready:
            raise RuntimeError("engine not ready")
        mid = req("/v1/models")[1]["data"][0]["id"]
        st, d = req("/v1/chat/completions", {"model": mid, "max_tokens": 24, "temperature": 0,
                                            "messages": [{"role": "user",
                                                          "content": "List three benefits of unit testing."}]})
        print("request http", st, "tokens", (d.get("usage") or {}).get("completion_tokens"))
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()


def parse(path):
    raw = open(path, "rb").read()
    T, W, RCOLS = struct.unpack_from("<iq i", raw, 0)
    off = 16
    off += 4 * T
    off += 4 * T * RCOLS

    def take(n):
        nonlocal off
        a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
        off += 2 * n
        return (a.astype(np.uint32) << 16).view(np.float32)

    ah = take(W * T).reshape(T, W)
    qn = take(256 * 16 * T)
    kn = take(256 * 4 * T)
    vv = take(256 * 4 * T)
    aa = take(256 * 16 * T)
    out = take(W * T).reshape(T, W)
    return T, W, RCOLS, ah, out


def main():
    run_dump()
    if not os.path.exists(DUMP):
        print("NO DUMP"); return
    T, W, RCOLS, ah, out_eng = parse(DUMP)
    print("dump T=%d W=%d rope_cols=%d ah_rms=%.4f out_rms=%.4f"
          % (T, W, RCOLS, float(np.sqrt((ah.astype(np.float64) ** 2).mean())),
             float(np.sqrt((out_eng.astype(np.float64) ** 2).mean()))))

    spec = importlib.util.spec_from_file_location("tr", os.path.join(BASE, "p3_mtp_train.py"))
    tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)
    sd = tr.load_file(HEAD) if hasattr(tr, "load_file") else None
    from safetensors.torch import load_file
    sd = load_file(HEAD)
    for k in list(sd):
        if k.endswith(".weight") and "norm" in k:
            sd[k] = sd[k].float() + 1.0
    layer = tr.M.MTPLayer(tr.CFG, sd).float().eval()

    # 只跑"层内"部分：input_norm → attn → mlp → final_norm（ah 已是 fc 之后）
    x = torch.from_numpy(ah).unsqueeze(0)
    with torch.no_grad():
        cos, sin = tr.M.rope_tables(layer.attn.head_dim, x.shape[1], layer.theta, x.device, x.dtype)
        h = x + layer.attn(layer.input_norm(x), cos, sin)[0]
        h = h + layer.mlp(layer.post_attention_norm(h))
        o = layer.final_norm(h)[0].numpy()
    a = o.reshape(-1).astype(np.float64)
    b = out_eng.reshape(-1).astype(np.float64)
    cosv = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    print("layer-out cosine(head, engine) = %.6f" % cosv)
    print("engine out rms=%.4f  head out rms=%.4f" % (b.std(), a.std()))


if __name__ == "__main__":
    main()
