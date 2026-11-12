# p3_vision_probe.py — P3：--vision 真实图文问答（生成左红右蓝 + 白方块的 PNG）
import base64
import json
import os
import struct
import subprocess
import sys
import time
import zlib
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 1841
IMG = os.path.join(WORK, "p3-vision-test.png")


def make_png(path, w=96, h=96):
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            if 36 <= x < 60 and 36 <= y < 60:
                row += bytes((255, 255, 255))
            elif x < w // 2:
                row += bytes((220, 40, 40))
            else:
                row += bytes((40, 60, 220))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


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


def http_json(port, path, payload=None, timeout=300):
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


size = make_png(IMG, 224, 224)
print("png bytes:", size)
with open(IMG, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
url = "data:image/png;base64," + b64

kill_own_engine()
time.sleep(0.6)
logp = os.path.join(WORK, "p3-vision.engine.log")
f = open(logp, "wb")
args = [EXE, MODEL, "--max-context", "8192", "--greedy", "--host-context-mib", "2048",
        "--prefill-chunk", "128", "--no-thinking", "--vision", "--port", str(PORT),
        "--log-level", "info"]
p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
try:
    ready = False
    for _ in range(240):
        time.sleep(0.5)
        if p.poll() is not None:
            break
        try:
            http_json(PORT, "/v1/models", timeout=2)
            ready = True
            break
        except Exception:
            pass
    if not ready:
        print("ENGINE NOT READY")
        with open(logp, "rb") as g:
            print(g.read()[-800:].decode("utf-8", "replace"))
        raise SystemExit(1)
    mid = http_json(PORT, "/v1/models")["data"][0]["id"]
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "What colors are on the left and right halves of this image? Answer briefly."},
        {"type": "image_url", "image_url": {"url": url}},
    ]}]
    t0 = time.time()
    try:
        d = http_json(PORT, "/v1/chat/completions",
                      {"model": mid, "messages": msgs, "max_tokens": 32,
                       "temperature": 0, "stream": False})
        t = d["choices"][0]["message"].get("content") or ""
        print("[vision] %.2fs chars=%d >>> %s" % (time.time() - t0, len(t),
                                                  " ".join(t.split())[:140]))
    except Exception as e:
        print("[vision] ERR %r" % e)
finally:
    try:
        p.kill()
    except Exception:
        pass
    f.close()
    time.sleep(0.4)
    kill_own_engine()
print("remaining:", ninfer_processes())
