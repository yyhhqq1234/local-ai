# p3_vision_url_probe.py — Recheck the local HTTP(S) vision path with the established test JPEG
import json
import os
import subprocess
import time
import http.client
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from threading import Thread

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
IMAGE = os.path.join(WORK, "test.jpg")
WEB_PORT = 18889
ENGINE_PORT = 18890

PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def ninfer_processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own_engine():
    for pid, path in ninfer_processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def http_json(port, path, payload=None, timeout=300):
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
        content_type = response.getheader("Content-Type", "")
        if "application/json" not in content_type:
            return {"http_status": response.status, "content_type": content_type,
                    "bytes": len(raw), "body": raw}
        return json.loads(raw)
    finally:
        c.close()


if not os.path.isfile(IMAGE):
    raise FileNotFoundError(IMAGE)

server = ThreadingHTTPServer(("127.0.0.1", WEB_PORT),
                             partial(SimpleHTTPRequestHandler, directory=WORK))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
web_result = http_json(WEB_PORT, "/test.jpg")
print("web bytes:", os.path.getsize(IMAGE), "url:", f"http://127.0.0.1:{WEB_PORT}/test.jpg")

log_path = os.path.join(WORK, "p3-vision-url.engine.log")
with open(log_path, "wb") as log:
    kill_own_engine()
    proc = subprocess.Popen(
        [EXE, MODEL, "--max-context", "2048", "--kv-capacity", "2048", "--greedy",
         "--host-context-mib", "0", "--device-state-slots", "0", "--no-cuda-graph",
         "--prefill-chunk", "128", "--no-thinking", "--vision", "--port", str(ENGINE_PORT),
         "--log-level", "info"],
        stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    ready = False
    try:
        for _ in range(300):
            time.sleep(0.4)
            if proc.poll() is not None:
                break
            try:
                models = http_json(ENGINE_PORT, "/v1/models", timeout=2)
                if isinstance(models, dict) and "data" in models:
                    ready = True
                    break
            except Exception:
                pass
        print("engine ready:", ready)
        if ready:
            model_id = http_json(ENGINE_PORT, "/v1/models")["data"][0]["id"]
            payload = {
                "model": model_id,
                "max_tokens": 48,
                "temperature": 0,
                "stream": False,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "What colors are visible, and where is the white square? Answer briefly."},
                    {"type": "image_url", "image_url": {"url": f"http://127.0.0.1:{WEB_PORT}/test.jpg"}},
                ]}],
            }
            started = time.perf_counter()
            result = http_json(ENGINE_PORT, "/v1/chat/completions", payload, timeout=300)
            elapsed = round(time.perf_counter() - started, 3)
            print("vision elapsed:", elapsed)
            print("vision result:", json.dumps(result, ensure_ascii=False)[:1200])
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        time.sleep(0.5)
        kill_own_engine()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

print("remaining ninfer:", ninfer_processes())
