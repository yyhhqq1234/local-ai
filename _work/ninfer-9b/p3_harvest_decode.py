# p3_harvest_decode.py — 采「decode 域」hidden（NINFER_TRACE_AR 逐轮追加 bf16 hidden）+ 生成 token ids
# 用法：python p3_harvest_decode.py <n_requests> [out_dir]
# 对齐假设：ar 第 i 条 ↔ 第 i 个生成 token 的 hidden；目标为第 i+1 个生成 token
import json
import os
import struct
import subprocess
import sys
import time
import http.client
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-mtp2f-GSQ.ninfer")
BASE = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18997
W = 4096
MAXTOK = 160

PROMPTS = [
    "Explain why local inference is useful. Give a detailed answer with examples.",
    "List three benefits of unit testing, each with one sentence.",
    "Write a short guide on how to reverse a Python list.",
    "用中文写一段关于本地推理优点的说明，约 150 字。",
    "What is a gated delta network? Explain in simple terms.",
    "Give a step-by-step plan for debugging a memory leak in C++.",
    "Summarize what a transformer attention layer does.",
    "用三条要点说明如何做一次内存扫描。",
]

PS = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
      "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def kill_own():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].strip().lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", p[0].strip(), "/F"], capture_output=True)


def req(path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse(); raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "mtp-decode")
    os.makedirs(outdir, exist_ok=True)
    ar = os.path.join(outdir, "_ar.bin")
    rl = os.path.join(outdir, "_req.jsonl")
    env = dict(os.environ)
    env["NINFER_TRACE_AR"] = ar
    env["NINFER_PREFILL_MAX_TOKENS"] = "64"
    for p in (ar, rl):
        if os.path.exists(p):
            os.remove(p)
    kill_own(); time.sleep(0.5)
    fh = open(os.path.join(BASE, "harvest-decode.log"), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT),
            "--request-log-jsonl", rl]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    meta = []
    try:
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                print("engine died"); return
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    break
            except Exception:
                pass
        mid = req("/v1/models")[1]["data"][0]["id"]
        for i in range(n):
            before = os.path.getsize(ar) if os.path.exists(ar) else 0
            prompt = PROMPTS[i % len(PROMPTS)]
            st, d = req("/v1/chat/completions", {"model": mid, "max_tokens": MAXTOK,
                                                "temperature": 0,
                                                "messages": [{"role": "user", "content": prompt}]})
            after = os.path.getsize(ar) if os.path.exists(ar) else 0
            recs = (after - before) // (W * 2)
            gen = (d.get("usage") or {}).get("completion_tokens")
            meta.append({"i": i, "byte0": before, "recs": recs, "gen": gen})
            print("req %d: gen=%s recs=%s" % (i, gen, recs)); sys.stdout.flush()
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()

    # 汇总：把 ar 全部读出来 + 从 reqlog 取每条的 generated_token_ids
    raw = open(ar, "rb").read()
    total = len(raw) // (W * 2)
    arr = np.frombuffer(raw, dtype=np.uint16, count=total * W).reshape(total, W)
    gens = []
    if os.path.exists(rl):
        for line in open(rl, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") == "request_done":
                ids = (d.get("result") or {}).get("generated_token_ids") or []
                gens.append(ids)
    print("ar records:", total, "requests logged:", len(gens))
    # 每请求的 hidden 段 = recs_i，ids 段 = gen_i；配对 hidden[t] ↔ ids[t]，目标 ids[t+1]
    off = 0
    saved = 0
    for k, ids in enumerate(gens):
        seg = len(ids) - 1
        if seg <= 0 or off + seg > total:
            break
        h = arr[off:off + seg]
        lab = np.array(ids[:seg], dtype=np.int32)
        tgt = np.array(ids[1:seg + 1], dtype=np.int32)
        np.savez_compressed(os.path.join(outdir, "d%04d.npz" % k), hidden=h, ids=lab, tgt=tgt)
        off += seg
        saved += 1
    print("saved npz:", saved, "tokens:", off)


if __name__ == "__main__":
    main()
