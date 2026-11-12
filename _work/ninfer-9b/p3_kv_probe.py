# p3_kv_probe.py — 本地配置探测：KV dtype / lm-head 分支对 system 乱码的影响
# 纪律：只按 Path 杀本档位引擎。
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
BASE = ["--max-context", "4096", "--greedy", "--host-context-mib", "2048",
        "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse"]

VARIANTS = [
    ("kv-bf16", ["--kv-dtype", "bf16"], 1691),
    ("kv-int8", ["--kv-dtype", "int8"], 1692),
    ("kv-fp8", ["--kv-dtype", "fp8"], 1693),
    ("kv-nvfp4", ["--kv-dtype", "nvfp4"], 1694),
    ("kv-k8v4", ["--kv-dtype", "k8v4"], 1695),
    ("lm-head-draft", ["--lm-head-draft"], 1696),
]

SYS = [{"role": "system", "content": "You are a helpful assistant."},
       {"role": "user", "content": "What is 2+2?"}]
USER = [{"role": "user", "content": "What is 2+2?"}]

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


def run(name, extra, port):
    kill_own_engine()
    time.sleep(0.7)
    log = os.path.join(WORK, "p3-kv-%s.engine.log" % name)
    f = open(log, "wb")
    p = subprocess.Popen([EXE, MODEL, "--port", str(port)] + BASE + extra,
                         stdout=f, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    res = {"name": name, "extra": extra, "ready": False, "sys": None, "user": None}
    try:
        ready = False
        last = ""
        for _ in range(100):
            time.sleep(0.4)
            if p.poll() is not None:
                last = "exit %s" % p.poll()
                break
            try:
                http_json(port, "/v1/models", timeout=2)
                ready = True
                break
            except Exception as e:
                last = repr(e)
        if not ready:
            res["error"] = "NOT READY " + last
            with open(log, "rb") as g:
                res["log_tail"] = g.read()[-600:].decode("utf-8", "replace")
            return res
        res["ready"] = True
        mid = http_json(port, "/v1/models")["data"][0]["id"]
        for key, msgs in (("sys", SYS), ("user", USER)):
            try:
                d = http_json(port, "/v1/chat/completions",
                              {"model": mid, "messages": msgs, "max_tokens": 16,
                               "temperature": 0, "stream": False})
                t = d["choices"][0]["message"]["content"] or ""
                res[key] = " ".join(t.split())[:95]
            except Exception as e:
                res[key] = "ERR " + repr(e)
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
    print("[%-14s] ready=%s err=%s" % (name, r["ready"], r.get("error", "")))
    print("     sys : %s" % r["sys"])
    print("     user: %s" % r["user"])

kill_own_engine()
out = os.path.join(WORK, "p3-kv-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_res, "remaining": ninfer_processes()}, f,
              ensure_ascii=False, indent=2)
print("remaining:", ninfer_processes())
print("result:", out)
