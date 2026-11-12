# p3_slots_probe.py — 本地配置优化：增大 device-state-slots 是否消除 base>=16 的污染
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
BASE = ["--max-context", "4096", "--greedy", "--prefill-chunk", "128", "--no-thinking",
        "--no-prefix-reuse"]
VARIANTS = [
    ("slots1", ["--device-state-slots", "1", "--host-context-mib", "2048"], 1721),
    ("slots2", ["--device-state-slots", "2", "--host-context-mib", "2048"], 1722),
    ("slots4", ["--device-state-slots", "4", "--host-context-mib", "2048"], 1723),
    ("slots8", ["--device-state-slots", "8", "--host-context-mib", "2048"], 1724),
    ("slots16", ["--device-state-slots", "16", "--host-context-mib", "2048"], 1725),
    ("slots8-host4096", ["--device-state-slots", "8", "--host-context-mib", "4096"], 1726),
]
CASES = [
    ("user19", [{"role": "user", "content": "What is 2+2?"}]),
    ("user20", [{"role": "user", "content": "Hi What is 2+2?"}]),
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}]),
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


def run(name, extra, port):
    kill_own_engine()
    time.sleep(0.7)
    logp = os.path.join(WORK, "p3-slots-%s.engine.log" % name)
    f = open(logp, "wb")
    p = subprocess.Popen([EXE, MODEL, "--port", str(port)] + BASE + extra,
                         stdout=f, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    res = {"name": name, "ready": False}
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
            res["error"] = "NOT READY"
            with open(logp, "rb") as g:
                res["tail"] = g.read()[-400:].decode("utf-8", "replace")
            return res
        res["ready"] = True
        mid = http_json(port, "/v1/models")["data"][0]["id"]
        for label, msgs in CASES:
            try:
                d = http_json(port, "/v1/chat/completions",
                              {"model": mid, "messages": msgs, "max_tokens": 8,
                               "temperature": 0, "stream": False})
                t = " ".join((d["choices"][0]["message"]["content"] or "").split())[:70]
                res[label] = t
            except Exception as e:
                res[label] = "ERR " + repr(e)
        time.sleep(0.4)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        f.close()
        time.sleep(0.4)
        kill_own_engine()
    return res


all_res = []
for name, extra, port in VARIANTS:
    r = run(name, extra, port)
    all_res.append(r)
    if not r["ready"]:
        print("[%-16s] NOT READY %s" % (name, r.get("tail", "")[:150]))
        continue
    ok19 = "4" in r.get("user19", "")
    ok20 = "4" in r.get("user20", "") and "equals" in r.get("user20", "")
    oksys = "4" in r.get("sys", "") and "equals" in r.get("sys", "")
    print("[%-16s] u19=%-5s u20=%-5s sys=%-5s" % (name, ok19, ok20, oksys))
    print("     u19 : %s" % r.get("user19"))
    print("     u20 : %s" % r.get("user20"))
    print("     sys : %s" % r.get("sys"))
kill_own_engine()
out = os.path.join(WORK, "p3-slots-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_res, "remaining": ninfer_processes()}, f,
              ensure_ascii=False, indent=2)
print("remaining:", ninfer_processes())
print("result:", out)
