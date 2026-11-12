# p3_mtp_block_dump.py — run one short request with the MTP block dump enabled
import json
import os
import subprocess
import time
import http.client

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18941
DUMP = os.path.join(WORK, "p3-mtp-block.bin")
ENGLOG = os.path.join(WORK, "p3-mtp-block.engine.log")
PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own():
    for pid, path in processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def request(port, path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        response = c.getresponse()
        raw = response.read()
        if response.status >= 400:
            return {"http_status": response.status, "body": raw.decode("utf-8", "replace")}
        return json.loads(raw)
    finally:
        c.close()


for path in (DUMP, ENGLOG):
    if os.path.exists(path):
        os.remove(path)

kill_own()
env = dict(os.environ)
env["NINFER_TRACE_MTP_BLOCK"] = DUMP
log = open(ENGLOG, "wb")
proc = subprocess.Popen(
    [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
     "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking", "--no-cuda-graph",
     "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT), "--log-level", "info"],
    stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    ready = False
    for _ in range(240):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        try:
            models = request(PORT, "/v1/models", timeout=2)
            if isinstance(models, dict) and "data" in models:
                ready = True
                break
        except Exception:
            pass
    print("ready:", ready)
    if ready:
        model_id = request(PORT, "/v1/models")["data"][0]["id"]
        response = request(PORT, "/v1/chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content": "List three benefits of unit testing."}],
            "max_tokens": 8,
            "temperature": 0,
            "stream": False,
        }, timeout=600)
        print("timings:", json.dumps(response.get("timings"), ensure_ascii=False))
finally:
    try:
        proc.kill()
    except Exception:
        pass
    log.close()
    time.sleep(0.5)
    kill_own()

with open(ENGLOG, encoding="utf-8", errors="replace") as f:
    for line in f:
        if "mtp-block" in line:
            print(line.rstrip())
print("dump exists:", os.path.exists(DUMP),
      os.path.getsize(DUMP) if os.path.exists(DUMP) else 0)
