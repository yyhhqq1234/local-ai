# p3_long_prefill.py — 量化 max_unit_tokens 对长 prompt prefill 的影响
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
LIMITS = [12, 15, 128]
CONTENT = ("The quick brown fox jumps over the lazy dog. " * 60).strip()
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


def parse(reqlog):
    if not os.path.exists(reqlog):
        return None
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
            return {
                "prompt_tokens": pt,
                "prefill_s": round(pf, 3),
                "prefill_tok_s": round(pt / pf, 1) if pf else None,
                "decode_tok_s": round(ct / dec, 1) if dec else None,
                "units": d.get("engine_timing", {}).get("units", {}).get("prefill"),
            }
    return None


def run(limit, port):
    kill_own_engine()
    time.sleep(0.6)
    reqlog = os.path.join(WORK, "p3-long-%d.reqlog.jsonl" % limit)
    logp = os.path.join(WORK, "p3-long-%d.engine.log" % limit)
    for p in (reqlog, logp):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env["NINFER_PREFILL_MAX_TOKENS"] = str(limit)
    f = open(logp, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse",
            "--port", str(port), "--request-log-jsonl", reqlog, "--log-level", "info"]
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    out = {"limit": limit, "ready": False}
    try:
        ready = False
        for _ in range(150):
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
        t0 = time.time()
        d = http_json(port, "/v1/chat/completions",
                      {"model": mid, "messages": [{"role": "user", "content": CONTENT}],
                       "max_tokens": 8, "temperature": 0, "stream": False})
        out["wall_s"] = round(time.time() - t0, 2)
        out["text"] = " ".join((d["choices"][0]["message"]["content"] or "").split())[:70]
        time.sleep(0.4)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        f.close()
        time.sleep(0.4)
        kill_own_engine()
    out.update(parse(reqlog) or {})
    return out


res = []
for i, limit in enumerate(LIMITS):
    r = run(limit, 1740 + i)
    res.append(r)
    if not r.get("ready"):
        print("limit=%-4d NOT READY" % limit)
        continue
    print("limit=%-4d prompt=%-5s units=%-4s prefill=%-7s tok/s (%-6ss) decode=%-6s wall=%-6ss | %s" %
          (limit, r.get("prompt_tokens"), r.get("units"), r.get("prefill_tok_s"),
           r.get("prefill_s"), r.get("decode_tok_s"), r.get("wall_s"), r.get("text")))
kill_own_engine()
out = os.path.join(WORK, "p3-long-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": res, "remaining": ninfer_processes()}, f, ensure_ascii=False, indent=2)
print("remaining:", ninfer_processes())
print("result:", out)
