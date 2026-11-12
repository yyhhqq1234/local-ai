import os
import sys
import time
import urllib.request

URL = ("https://hf-mirror.com/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/"
       "Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf")
OUT = r"E:\staging-27b\Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf"

os.makedirs(os.path.dirname(OUT), exist_ok=True)
have = os.path.getsize(OUT) if os.path.exists(OUT) else 0
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
if have:
    req.add_header("Range", "range=%d-" % have)
r = urllib.request.urlopen(req, timeout=120)
total = int(r.headers.get("Content-Length") or 0) + have
mode = "ab" if have else "wb"
t0 = time.time()
last = 0
with open(OUT, mode) as f:
    while True:
        chunk = r.read(1024 * 1024 * 4)
        if not chunk:
            break
        f.write(chunk)
        have += len(chunk)
        now = time.time()
        if now - last > 15:
            last = now
            rate = have / max(1e-6, now - t0) / 1e6
            print("progress %.2f/%.2f GB  %.1f MB/s" % (have / 1e9, total / 1e9, rate), flush=True)
print("done", have, "bytes in %.0fs" % (time.time() - t0))
