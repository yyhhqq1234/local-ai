# p3_p0_limit_trace.py — P0 第一步：同一 prompt 在 limit=12（正常）与 16（乱码）下的 kernel 序列对比
import json
import os
import re
import subprocess
import sys
import time
import http.client
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PROMPT = "Hi What is 2+2?"
CASES = [("lim12", 12, 1801), ("lim16", 16, 1802)]
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


def http_json(port, path, payload=None, timeout=120):
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


def run(label, limit, port):
    kill_own_engine()
    time.sleep(0.6)
    logp = os.path.join(WORK, "p3-p0-%s.engine.log" % label)
    env = dict(os.environ)
    env["NINFER_TRACE_SHAPES"] = "1"
    env["NINFER_PREFILL_MAX_TOKENS"] = str(limit)
    f = open(logp, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse",
            "--port", str(port), "--log-level", "info"]
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    text = ""
    try:
        for _ in range(150):
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
                      {"model": mid, "messages": [{"role": "user", "content": PROMPT}],
                       "max_tokens": 8, "temperature": 0, "stream": False})
        text = " ".join((d["choices"][0]["message"]["content"] or "").split())[:70]
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
    c = Counter()
    with open(logp, encoding="utf-8", errors="replace") as g:
        for line in g:
            m = re.search(r"\[(q8|bf16|conv)\][^\r\n]*", line)
            if m:
                c[m.group(0).strip()] += 1
    return text, c


res = {}
for label, limit, port in CASES:
    text, c = run(label, limit, port)
    res[label] = c
    print("[%s] out=%r trace_lines=%d unique=%d" % (label, text, sum(c.values()), len(c)))
    for line, n in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:12]:
        print("    %4d  %s" % (n, line))

a, b = res["lim12"], res["lim16"]
only12 = sorted(set(a) - set(b))
only16 = sorted(set(b) - set(a))
print("\n=== only in limit12 (%d) ===" % len(only12))
for x in only12[:40]:
    print("   %4d  %s" % (a[x], x))
print("\n=== only in limit16 (%d) ===" % len(only16))
for x in only16[:40]:
    print("   %4d  %s" % (b[x], x))
print("\n=== shared but count differs ===")
for x in sorted(set(a) & set(b)):
    if a[x] != b[x]:
        print("   12=%-4d 16=%-4d  %s" % (a[x], b[x], x))
kill_own_engine()
out = os.path.join(WORK, "p3-p0-trace-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({k: dict(v) for k, v in res.items()}, f, ensure_ascii=False, indent=2)
print("remaining:", ninfer_processes())
print("result:", out)
