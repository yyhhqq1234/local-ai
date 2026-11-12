# p3_speed_sweep.py — 本地提速手段实测：KV 精度 / prefill 块宽 / 前缀复用 / 并发吞吐
# 每格独立起引擎（同一 exe、同一模型），只改一个变量；每格跑 1 次 256-token greedy 生成。
import json
import os
import subprocess
import sys
import time
import threading
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18950
OUT = os.path.join(WORK, "p3-speed-sweep.json")
PROMPT = "Explain why local inference is useful. Give a detailed answer with examples."
MAXTOK = 256

BASE = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
        "--no-thinking", "--port", str(PORT)]

# (名字, 额外参数, 并发数)
CONFIGS = [
    ("base", [], 1),
    ("kv-int8", ["--kv-dtype", "int8"], 1),
    ("kv-fp8", ["--kv-dtype", "fp8"], 1),
    ("kv-k8v4", ["--kv-dtype", "k8v4"], 1),
    ("chunk-256", ["--prefill-chunk", "256"], 1),
    ("chunk-512", ["--prefill-chunk", "512"], 1),
    ("no-prefix-reuse", ["--no-prefix-reuse"], 1),
    ("concurrency-4", [], 4),
]

PS_LIST = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
           "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def procs():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own():
    for pid, p in procs():
        if p.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def req(path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return json.loads(r.read())
    finally:
        c.close()


def run_one(mid, ntok):
    t0 = time.perf_counter()
    d = req("/v1/chat/completions", {"model": mid,
                                    "messages": [{"role": "user", "content": PROMPT}],
                                    "max_tokens": ntok, "temperature": 0, "stream": False})
    wall = time.perf_counter() - t0
    tm = d.get("timings") or {}
    return {"wall": round(wall, 3),
            "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"),
            "completion_tokens": (d.get("usage") or {}).get("completion_tokens"),
            "ttft": round(tm.get("prompt_ms", 0) / 1000.0, 3),
            "prefill_tok_s": tm.get("prompt_per_second"),
            "decode_tok_s": tm.get("predicted_per_second")}


rows = []
for name, extra, conc in CONFIGS:
    kill_own()
    time.sleep(1.0)
    argv = list(BASE)
    argv += extra if "--prefill-chunk" in extra else (["--prefill-chunk", "128"] + extra)
    fh = open(os.path.join(WORK, "p3-speed-%s.engine.log" % name), "wb")
    proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    row = {"config": name, "extra": extra, "concurrency": conc, "ready": False}
    try:
        for _ in range(240):
            time.sleep(0.5)
            if proc.poll() is not None:
                row["died"] = True
                break
            try:
                m = req("/v1/models", timeout=2)
                if isinstance(m, dict) and "data" in m:
                    row["ready"] = True
                    break
            except Exception:
                pass
        if row["ready"]:
            mid = req("/v1/models")["data"][0]["id"]
            if conc == 1:
                row.update(run_one(mid, MAXTOK))
            else:
                res = [None] * conc

                def w(i):
                    res[i] = run_one(mid, MAXTOK // conc)

                t0 = time.perf_counter()
                ts = [threading.Thread(target=w, args=(i,)) for i in range(conc)]
                [t.start() for t in ts]
                [t.join() for t in ts]
                wall = time.perf_counter() - t0
                tot = sum((x or {}).get("completion_tokens") or 0 for x in res)
                row.update({"wall": round(wall, 3), "completion_tokens": tot,
                            "aggregate_tok_s": round(tot / wall, 2) if wall else None,
                            "per_stream_tok_s": [round((x or {}).get("decode_tok_s") or 0, 1) for x in res]})
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        fh.close()
        time.sleep(0.5)
        kill_own()
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False))
    sys.stdout.flush()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"prompt": PROMPT, "max_tokens": MAXTOK, "rows": rows}, f, ensure_ascii=False, indent=2)
print("saved:", OUT)
