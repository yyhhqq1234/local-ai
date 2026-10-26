#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_speed.py - v4 download-speed probe (READ-ONLY).

Never touches PID 1312/1363. Only:
  a) ModelScope / HF-mirror search API for third-party abliterated 27B uploads
  b) throughput of candidate HF mirror domains (8 MiB range x2 rounds)
  c) baseline: ModelScope official Qwen/Qwen3.8-27B shard (8 MiB range x2)

Run:  /root/miniconda3/bin/python -u probe_speed.py
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

MB = 1048576.0
RANGE = "0-8388607"  # 8 MiB
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
FILE = "model-00001-of-00018.safetensors"
MS_QWEN = "Qwen/Qwen3.8-27B"
BASE = "/root/autodl-tmp/kitty-rev"
SHARD1 = os.path.join(BASE, "base/Huihui", FILE)


def sh(cmd, t=30):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return "[ERR] %s" % e


def cut(txt, n=1200):
    return txt[:n] if txt else "(empty)"


def http_get(url, t=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=t) as r:
            return r.status, r.read(300000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:
        return -1, "[ERR] %s: %s" % (type(e).__name__, e)


def probe(url, cap=40):
    """curl one 8 MiB range -> (MiB/s, http_code, got_bytes, secs, note)."""
    cmd = ["curl", "-sS", "-L", "--max-time", str(cap),
           "-r", RANGE, "-o", "/dev/null",
           "-H", "User-Agent: " + UA,
           "-w", "%{speed_download} %{http_code} %{size_download} %{time_total}",
           url]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=cap + 25)
        o = (p.stdout or "").strip().split()
        if len(o) >= 3:
            spd = float(o[0]) / MB
            code = o[1]
            nb = int(float(o[2]))
            sec = float(o[3]) if len(o) > 3 else time.time() - t0
            note = ""
            if nb < 8000000:
                note = "short(%d)" % nb
            return spd, code, nb, sec, note
        return 0.0, "PARSE", 0, time.time() - t0, repr((p.stdout or p.stderr or "")[:60])
    except subprocess.TimeoutExpired:
        return 0.0, "HARDTIMEOUT", 0, time.time() - t0, ""


def size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


# ---------------------------------------------------------------- section 0
def sec0():
    print("=" * 72)
    print("[0] LIVE SNAPSHOT (read-only)  %s" % time.strftime("%F %T"))
    print("=" * 72)
    print("-- processes --")
    print(sh("ps -eo pid,ppid,etime,cmd | grep -E '[d]l_huihui|[c]url|[t]rain_kitty|[p]recompute' || echo none"))
    print("-- shard1 --")
    s = size_of(SHARD1)
    print("%s = %s bytes (%.3f GB)" % (FILE, s, s / 1e9 if s > 0 else 0))
    print("-- dir --")
    print(sh("ls -l %s/base/Huihui/*.safetensors 2>/dev/null | wc -l; du -sh %s/base/Huihui 2>/dev/null" % (BASE, BASE)))
    print("-- disk --")
    print(sh("df -h /root/autodl-tmp | tail -2"))
    print("-- gpu --")
    print(sh("nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader"))
    print("-- dns --")
    for h in ("hf-mirror.com", "hf-mirror.net", "huggingface.sukaka.top",
              "hf.xeduapi.com", "modelscope.cn", "huggingface.co"):
        print("   %-26s %s" % (h, sh("getent hosts %s 2>/dev/null | head -1" % h).strip() or "(no resolve)"))
    return s


# ---------------------------------------------------------------- section a
def sec_a():
    print()
    print("=" * 72)
    print("[a] SEARCH: third-party abliterated 27B on ModelScope / HF-mirror")
    print("=" * 72)
    rows = [
        ("MS-dolphin-ablit", "https://modelscope.cn/api/v1/dolphin/models?PageSize=30&PageNumber=1&Name=abliterated"),
        ("MS-v1-ablit", "https://modelscope.cn/api/v1/models?PageSize=30&PageNumber=1&Name=abliterated"),
        ("MS-dolphin-q3827", "https://modelscope.cn/api/v1/dolphin/models?PageSize=30&PageNumber=1&Name=Qwen3.8-27B"),
        ("HFM-author-huihui", "https://hf-mirror.com/api/models?author=huihui-ai&limit=100"),
        ("HFM-search-ablit", "https://hf-mirror.com/api/models?search=Qwen3.8-27B-abliterated&limit=100"),
        ("HUGGINGFACE-api", "https://huggingface.co/api/models?author=huihui-ai&limit=100"),
    ]
    found = []
    for tag, url in rows:
        code, body = http_get(url)
        print("--- %-18s HTTP %s  len=%d  %s" % (tag, code, len(body), url))
        print("    " + cut(body, 700).replace("\n", " ")[:700])
        ids = sorted(set(re.findall(r'"(?:id|ModelId|Path|Name)"\s*:\s*"([^"]{3,140})"', body)))
        if ids:
            hit = [i for i in ids if "27" in i or "ablit" in i.lower() or "huihui" in i.lower()]
            print("    ids[%d] hit[%d]: %s" % (len(ids), len(hit), hit[:40]))
            found.extend(hit)
        print()
    # explicit probe: is the repo itself on ModelScope?
    for u in ("https://modelscope.cn/api/v1/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated",
              "https://modelscope.cn/api/v1/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated/repo/files?Revision=master&Root="):
        code, body = http_get(u)
        print("--- MS-explicit HTTP %s  %s" % (code, u))
        print("    " + cut(body, 500))
    return sorted(set(found))


# ---------------------------------------------------------------- section b
def sec_b(rounds=2):
    print()
    print("=" * 72)
    print("[b] MIRROR THROUGHPUT  (%s range, %d rounds, cap 40s)" % (RANGE, rounds))
    print("=" * 72)
    mirrors = [
        ("hf-mirror.com", "https://hf-mirror.com/%s/resolve/main/%s" % (REPO, FILE)),
        ("hf-mirror.net", "https://hf-mirror.net/%s/resolve/main/%s" % (REPO, FILE)),
        ("hf.sukaka.top", "https://huggingface.sukaka.top/%s/resolve/main/%s" % (REPO, FILE)),
        ("hf.xeduapi.com", "https://hf.xeduapi.com/%s/resolve/main/%s" % (REPO, FILE)),
        ("modelscope-huihui", "https://modelscope.cn/models/%s/resolve/master/%s" % (REPO, FILE)),
        ("hf.co-direct", "https://huggingface.co/%s/resolve/main/%s" % (REPO, FILE)),
    ]
    res = {}
    for r in range(1, rounds + 1):
        print("-- round %d --" % r)
        for name, url in mirrors:
            spd, code, nb, sec, note = probe(url)
            res.setdefault(name, []).append((spd, code, nb, sec, note))
            print("   %-18s %7.2f MiB/s  HTTP %-4s  got %9d B  %.1fs %s"
                  % (name, spd, code, nb, sec, note))
            sys.stdout.flush()
    print()
    print("-- summary (mean of %d rounds) --" % rounds)
    out = []
    for name, url in mirrors:
        vals = res.get(name, [])
        good = [v[0] for v in vals if v[2] > 1000000]
        mean = sum(good) / len(good) if good else 0.0
        codes = ",".join(str(v[1]) for v in vals)
        out.append((name, mean, codes, max([v[0] for v in vals] or [0])))
        print("   %-18s mean %7.2f MiB/s  peak %7.2f  codes=%s"
              % (name, mean, max([v[0] for v in vals] or [0]), codes))
    return out


# ---------------------------------------------------------------- section c
def sec_c(rounds=2):
    print()
    print("=" * 72)
    print("[c] BASELINE: ModelScope official %s (known-fast source)" % MS_QWEN)
    print("=" * 72)
    code, body = http_get("https://modelscope.cn/api/v1/models/%s/repo/files?Revision=master&Root=" % MS_QWEN)
    print("-- file list API HTTP %s len=%d" % (code, len(body)))
    cand = []
    if code == 200:
        try:
            j = json.loads(body)
            files = (j.get("Data") or {}).get("Files") or []
            for f in files:
                p = f.get("Path") or f.get("Name") or ""
                if p.endswith(".safetensors"):
                    cand.append(p)
        except Exception as e:
            print("   json parse err: %s" % e)
    print("   safetensors found: %d  head=%s" % (len(cand), cand[:5]))
    if not cand:
        cand = ["model-00001-of-00018.safetensors", "model-00001-of-00009.safetensors",
                "model-00001-of-00004.safetensors"]
        print("   fallback guesses: %s" % cand)
    urls = [("MS-%s" % p, "https://modelscope.cn/models/%s/resolve/master/%s" % (MS_QWEN, p))
            for p in cand[:3]]
    res = {}
    for r in range(1, rounds + 1):
        print("-- round %d --" % r)
        for name, url in urls:
            spd, c2, nb, sec, note = probe(url)
            res.setdefault(name, []).append((spd, c2, nb, sec, note))
            print("   %-40s %7.2f MiB/s  HTTP %-4s  got %9d B  %.1fs %s"
                  % (name[:40], spd, c2, nb, sec, note))
            sys.stdout.flush()
    print()
    out = []
    for name, url in urls:
        vals = res.get(name, [])
        good = [v[0] for v in vals if v[2] > 1000000]
        mean = sum(good) / len(good) if good else 0.0
        out.append((name, mean, ",".join(str(v[1]) for v in vals)))
        print("   %-40s mean %7.2f MiB/s  codes=%s" % (name[:40], mean, out[-1][2]))
    return out


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    s_before = sec0()
    ids = sec_a()
    mb = sec_b(2)
    mc = sec_c(2)
    s_after = size_of(SHARD1)
    dt = time.time() - t0

    print()
    print("=" * 72)
    print("[z] VERDICT")
    print("=" * 72)
    print("probe wall time: %.1fs" % dt)
    if s_before > 0 and s_after > 0:
        grow = s_after - s_before
        print("shard1 grew %d B during probe -> %.2f MiB/s AVERAGE for the live curl"
              % (grow, grow / MB / dt))
    print()
    base_mean = 0.0
    for name, mean, codes in mc:
        if mean > base_mean:
            base_mean = mean
    print("ModelScope baseline (best shard) = %.2f MiB/s" % base_mean)
    print()
    for name, mean, codes, peak in mb:
        tag = "??"
        if mean >= 5.0:
            tag = "FAST(>=5)"
        elif mean >= 3.0:
            tag = "OK(>=3)"
        elif mean >= 1.0:
            tag = "SLOW"
        else:
            tag = "DEAD"
        print("   %-20s %6.2f MiB/s  %s  codes=%s" % (name, mean, tag, codes))
    print()
    if base_mean >= 5.0:
        print(">>> ModelScope is FAST (%.1f MiB/s) => instance egress is NOT the bottleneck." % base_mean)
        print(">>> hf-mirror path is mirror-limited. Switching source HAS value.")
    elif base_mean >= 3.0:
        print(">>> ModelScope is OK (%.1f MiB/s) => egress roughly usable." % base_mean)
    elif base_mean > 0.5:
        print(">>> ModelScope is SLOW (%.1f MiB/s) => likely INSTANCE EGRESS THROTTLE." % base_mean)
        print(">>> Other mirrors will not help much; waiting is the only path.")
    else:
        print(">>> ModelScope also unreachable/slow => inconclusive; check network.")
    if ids:
        print()
        print(">>> search hits (%d): %s" % (len(ids), ids[:30]))
    print()
    print("[z] END %s" % time.strftime("%F %T"))


if __name__ == "__main__":
    main()
