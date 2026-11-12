# p3_long_system.py — 长 system（模拟 DSH 真实会话）是否仍乱码 + prefill 速度
import json
import os
import subprocess
import sys
import time
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 1821
SYSTEM = ("You are a careful local assistant. Follow the operator's instructions exactly, "
          "keep answers short, and never invent tool results. ") * 20
CASES = [
    ("long-sys", [{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": "What is 2+2?"}], 16),
    ("long-sys-essay", [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
]
PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def ninfer_processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[0].strip().isdigit():
            out.append((int(p[0].strip()), p[1].strip()))
    return out


def kill_own_engine():
    for pid, path in ninfer_processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def http_json(port, path, payload=None, timeout=180):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        return json.loads(c.getresponse().read())
    finally:
        c.close()


kill_own_engine()
time.sleep(0.6)
reqlog = os.path.join(WORK, "p3-longsys.reqlog.jsonl")
logp = os.path.join(WORK, "p3-longsys.engine.log")
for p in (reqlog, logp):
    if os.path.exists(p):
        os.remove(p)
f = open(logp, "wb")
args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
        "--prefill-chunk", "128", "--no-thinking", "--port", str(PORT),
        "--request-log-jsonl", reqlog, "--log-level", "info"]
p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
try:
    for _ in range(150):
        time.sleep(0.4)
        if p.poll() is not None:
            break
        try:
            http_json(PORT, "/v1/models", timeout=2)
            break
        except Exception:
            pass
    mid = http_json(PORT, "/v1/models")["data"][0]["id"]
    for name, msgs, mt in CASES:
        try:
            d = http_json(PORT, "/v1/chat/completions",
                          {"model": mid, "messages": msgs, "max_tokens": mt,
                           "temperature": 0, "stream": False})
            t = d["choices"][0]["message"]["content"] or ""
            print("[%s] chars=%d >>> %s" % (name, len(t), " ".join(t.split())[:100]))
        except Exception as e:
            print("[%s] ERR %r" % (name, e))
    time.sleep(0.4)
finally:
    try:
        p.kill()
    except Exception:
        pass
    f.close()
    time.sleep(0.4)
    kill_own_engine()

if os.path.exists(reqlog):
    with open(reqlog, encoding="utf-8") as g:
        for line in g:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "request_done":
                continue
            r, t = d.get("result", {}), d.get("timings_seconds", {})
            pt, ct = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0
            pf, dec = t.get("prefill") or 0, t.get("decode") or 0
            print("req: prompt=%s prefill=%.1f tok/s (%.2fs) decode=%.1f tok/s units=%s" %
                  (pt, pt / pf if pf else 0, pf, ct / dec if dec else 0,
                   d.get("engine_timing", {}).get("units", {}).get("prefill")))
print("remaining:", ninfer_processes())
