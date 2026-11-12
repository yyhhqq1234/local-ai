# p3_p0_layers.py — P0：对比 limit=12 与 16 的逐层 hidden 统计，定位首个分叉层
import json
import math
import os
import re
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
NORM = os.path.join(ROOT, r"_tools\layer-norm.txt")
PROMPT = "Hi What is 2+2?"
CASES = [("12", 12, 1811), ("16", 16, 1812)]
LINE = re.compile(r"L(\d+)\s+(\w+)\s+T=(\d+)(?:\s+n=(\d+))?\s+nan=(\d+)\s+l2=([0-9.]+)")
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


def run(label, limit, port):
    kill_own_engine()
    time.sleep(0.6)
    if os.path.exists(NORM):
        os.remove(NORM)
    logp = os.path.join(WORK, "p3-p0layers-%s.engine.log" % label)
    env = dict(os.environ)
    env["NINFER_TRACE_LAYERS"] = "1"
    env["NINFER_PREFILL_MAX_TOKENS"] = str(limit)
    f = open(logp, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse",
            "--no-cuda-graph",
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
    rows = []
    if os.path.exists(NORM):
        import shutil
        shutil.copy2(NORM, os.path.join(WORK, "layer-norm-%s.txt" % label))
        with open(NORM, encoding="utf-8", errors="replace") as g:
            for line in g:
                m = LINE.search(line)
                if m:
                    rows.append({"layer": int(m.group(1)), "phase": m.group(2),
                                 "T": int(m.group(3)),
                                 "n": int(m.group(4)) if m.group(4) else 4096 * int(m.group(3)),
                                 "nan": int(m.group(5)), "l2": float(m.group(6))})
    return text, rows


data = {}
for label, limit, port in CASES:
    text, rows = run(label, limit, port)
    data[label] = rows
    print("[limit=%s] out=%r dump_rows=%d" % (label, text, len(rows)))

def by_t(rows, t):
    return {r["layer"]: r for r in rows if r["phase"] == "prefill" and r["T"] == t}

def main_t(rows):
    ts = [r["T"] for r in rows if r["phase"] == "prefill"]
    return max(ts) if ts else 0


ta, tb = main_t(data["12"]), main_t(data["16"])
print("\nmain T: 12-group=%d 16-group=%d" % (ta, tb))
a, b = by_t(data["12"], ta), by_t(data["16"], tb)
print("\nlayer | T12 rms      | T16 rms      | ratio")
print("------+--------------+--------------+------")
for layer in sorted(set(a) & set(b)):
    ra = a[layer]["l2"] / math.sqrt(max(a[layer]["n"], 1))
    rb = b[layer]["l2"] / math.sqrt(max(b[layer]["n"], 1))
    ratio = rb / ra if ra else 0.0
    flag = "  <== diverge" if ratio > 1.5 or ratio < 0.67 else ""
    print("L%02d   | %-12.5f | %-12.5f | %.3f%s" % (layer, ra, rb, ratio, flag))
print("\nT12 nan total:", sum(r["nan"] for r in data["12"] if r["phase"] == "prefill" and r["T"] == 12))
print("T16 nan total:", sum(r["nan"] for r in data["16"] if r["phase"] == "prefill" and r["T"] == 16))
kill_own_engine()
out = os.path.join(WORK, "p3-p0-layers-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("remaining:", ninfer_processes())
print("result:", out)
