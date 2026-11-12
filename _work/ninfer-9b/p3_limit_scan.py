# p3_limit_scan.py — 扫描 NINFER_PREFILL_MAX_TOKENS，找「不乱码」的最大上限与速度代价
import json
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
LIMITS = [8, 12, 15, 16, 20, 24, 28, 31, 32, 48, 64, 128]
BASE_PORT = 1740
CASES = [
    ("u19", [{"role": "user", "content": "What is 2+2?"}], 8),
    ("u20", [{"role": "user", "content": "Hi What is 2+2?"}], 8),
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}], 8),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
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


GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def garbled(t):
    if not t or "\ufffd" in t:
        return True
    m = GARBAGE.search(t)
    if m:
        s = m.group(0)
        if any(c.islower() for c in s) and any(c.isupper() for c in s):
            return True
    return False


def parse_speed(reqlog):
    if not os.path.exists(reqlog):
        return None, None
    with open(reqlog, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "request_done":
                continue
            r, t = d.get("result", {}), d.get("timings_seconds", {})
            pt, ct = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0
            pf, dec = t.get("prefill") or 0, t.get("decode") or 0
            return (round(pt / pf, 1) if pf else None,
                    round(ct / dec, 1) if dec else None)
    return None, None


def run(limit, port):
    kill_own_engine()
    time.sleep(0.6)
    reqlog = os.path.join(WORK, "p3-limit-%d.reqlog.jsonl" % limit)
    logp = os.path.join(WORK, "p3-limit-%d.engine.log" % limit)
    for p in (reqlog, logp):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env["NINFER_PREFILL_MAX_TOKENS"] = str(limit)
    f = open(logp, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--port", str(port),
            "--request-log-jsonl", reqlog, "--log-level", "info"]
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    out = {"limit": limit, "ready": False}
    try:
        ready = False
        for _ in range(120):
            time.sleep(0.4)
            if p.poll() is not None:
                break
            try:
                http_json(port, "/v1/models", timeout=2)
                ready = True
                break
            except Exception:
                pass
        if not ready:
            out["error"] = "NOT READY"
            return out
        out["ready"] = True
        mid = http_json(port, "/v1/models")["data"][0]["id"]
        for name, msgs, mt in CASES:
            try:
                d = http_json(port, "/v1/chat/completions",
                              {"model": mid, "messages": msgs, "max_tokens": mt,
                               "temperature": 0, "stream": False})
                t = d["choices"][0]["message"]["content"] or ""
                out[name] = " ".join(t.split())[:70]
                out[name + "_len"] = len(t)
            except Exception as e:
                out[name] = "ERR " + repr(e)
                out[name + "_len"] = 0
        time.sleep(0.4)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        f.close()
        time.sleep(0.4)
        kill_own_engine()
    out["prefill_tok_s"], out["decode_tok_s"] = parse_speed(reqlog)
    return out


results = []
for i, limit in enumerate(LIMITS):
    r = run(limit, BASE_PORT + i)
    results.append(r)
    if not r.get("ready"):
        print("limit=%-4d NOT READY" % limit)
        continue
    u20 = r.get("u20", "")
    sys = r.get("sys", "")
    essay = r.get("essay", "")
    ok = (("4" in u20 and ("equals" in u20 or "=" in u20)) and
          ("4" in sys and ("equals" in sys or "=" in sys)) and
          r.get("essay_len", 0) >= 60 and
          not any(garbled(x) for x in (r.get("u19", ""), u20, sys, essay)))
    r["ok"] = ok
    print("limit=%-4d ok=%-5s prefill=%-7s decode=%-6s | u20=%r | sys=%r | essay=%r" %
          (limit, ok, r.get("prefill_tok_s"), r.get("decode_tok_s"),
           u20[:38], sys[:38], essay[:42]))
kill_own_engine()
safe = [r["limit"] for r in results if r.get("ok")]
print("=== safe limits: %s ; max safe = %s ===" % (safe, max(safe) if safe else "NONE"))
print("remaining:", ninfer_processes())
out = os.path.join(WORK, "p3-limit-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": results, "safe": safe}, f, ensure_ascii=False, indent=2)
print("result:", out)
