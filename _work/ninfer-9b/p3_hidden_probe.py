# p3_hidden_probe.py — 二分定位：对比 prompt=19 / 20 的 prefill 末层 hidden
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
CASES = [("19", "What is 2+2?", 1711), ("20", "Hi What is 2+2?", 1712)]
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


def http_json(port, path, payload=None, timeout=60):
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


def run(label, content, port):
    kill_own_engine()
    time.sleep(0.7)
    logp = os.path.join(WORK, "p3-hidden-%s.engine.log" % label)
    env = dict(os.environ)
    env["NINFER_TRACE_HIDDEN"] = "1"
    env["NINFER_TRACE_SHAPES"] = "1"
    f = open(logp, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse",
            "--port", str(port), "--log-level", "info"]
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    text = ""
    try:
        for _ in range(120):
            time.sleep(0.4)
            if p.poll() is not None:
                break
            try:
                http_json(port, "/v1/models", timeout=2)
                break
            except Exception:
                pass
        mid = http_json(port, "/v1/models")["data"][0]["id"]
        d = http_json(port, "/v1/chat/completions",
                      {"model": mid, "messages": [{"role": "user", "content": content}],
                       "max_tokens": 8, "temperature": 0, "stream": False})
        text = " ".join((d["choices"][0]["message"]["content"] or "").split())[:80]
        time.sleep(0.4)
    except Exception as e:
        text = "ERR " + repr(e)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        f.close()
        time.sleep(0.4)
        kill_own_engine()
    lines = []
    with open(logp, encoding="utf-8", errors="replace") as g:
        for line in g:
            if "[hidden]" in line:
                lines.append(line.strip())
    return text, lines


for label, content, port in CASES:
    text, lines = run(label, content, port)
    print("[%s] out=%r hidden_lines=%d" % (label, text, len(lines)))
    for x in lines[:6]:
        print("    " + x)
kill_own_engine()
print("remaining:", ninfer_processes())
