import os
import time
import urllib.request

URL = ("https://hf-mirror.com/fyb1214/Huihui-Qwen3.8-27B-Abliterated-Swift-1.5-GSQ-RCO-NInfer/"
       "resolve/main/Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer")
OUT = r"E:\staging-27b\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer"
TOTAL = 0  # 未知就用 Content-Length

deadline = time.time() + 4 * 3600
attempt = 0
last_report = 0
while time.time() < deadline:
    have = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    if TOTAL and have >= TOTAL:
        print("complete", have, flush=True)
        break
    attempt += 1
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        r = urllib.request.urlopen(req, timeout=60)
        cl = int(r.headers.get("Content-Length") or 0)
        if r.status == 206:
            TOTAL = have + cl
        elif cl:
            TOTAL = cl
            have = 0
        mode = "ab" if (have and r.status == 206) else "wb"
        with open(OUT, mode) as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.time() - last_report > 20:
                    last_report = time.time()
                    print("progress %.2f/%.2f GB (try %d)" % (have / 1e9, (TOTAL or 0) / 1e9, attempt), flush=True)
    except Exception as e:
        print("retry %d: %s %s" % (attempt, type(e).__name__, str(e)[:60]), flush=True)
        time.sleep(5)

size = os.path.getsize(OUT) if os.path.exists(OUT) else 0
print("final", size, "target", TOTAL, flush=True)
