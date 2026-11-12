import os
import time
import urllib.request

URLS = [
    "https://hf-mirror.com/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf",
]
OUT = r"E:\staging-27b\Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ2_S-mtp.gguf"
TOTAL = 9607981056


def fetch(url, have):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    if have:
        req.add_header("Range", "bytes=%d-" % have)
    return urllib.request.urlopen(req, timeout=60)


deadline = time.time() + 3 * 3600
attempt = 0
while time.time() < deadline:
    have = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    if have >= TOTAL:
        print("complete", have, flush=True)
        break
    attempt += 1
    url = URLS[0]
    try:
        r = fetch(url, have)
        mode = "ab" if have and r.status == 206 else "wb"
        if mode == "wb":
            have = 0
        with open(OUT, mode) as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if int(have) % (256 * 1024 * 1024) < 512 * 1024:
                    print("progress %.2f/%.2f GB (try %d)" % (have / 1e9, TOTAL / 1e9, attempt), flush=True)
    except Exception as e:
        print("retry %d after %s: %s" % (attempt, type(e).__name__, str(e)[:60]), flush=True)
        time.sleep(5)

print("final bytes", os.path.getsize(OUT) if os.path.exists(OUT) else 0, flush=True)
