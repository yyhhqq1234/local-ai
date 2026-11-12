# p3_mtp2_probe.py — 新 MTP 头（mtp2 artifact）实测：无投机基线 / d1 / d2 / d3
import json, os, re, subprocess, sys, time, http.client
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-mtp2f-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18980
OUT = os.path.join(WORK, "p3-mtp2-result.json")
PROMPT = "Explain why local inference is useful. Give a detailed answer with examples."
MAXTOK = 256
ENV_UNIT = "64"   # 必须：否则 MTP prefill 在 128 单元上 bad_alloc

CONFIGS = [("no-spec", []), ("mtp-d1", ["--spec", "mtp", "--draft-tokens", "1"]),
           ("mtp-d2", ["--spec", "mtp", "--draft-tokens", "2"]),
           ("mtp-d3", ["--spec", "mtp", "--draft-tokens", "3"])]

PS = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
      "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def kill_own():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].strip().lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", p[0].strip(), "/F"], capture_output=True)


def req(path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def garbled(t):
    if not t.strip():
        return True, "empty"
    if "\ufffd" in t:
        return True, "replacement-char"
    if re.search(r"(.)\1{6,}", t):
        return True, "char-repeat"
    return False, ""


def trial(name, flags):
    kill_own(); time.sleep(0.5)
    env = dict(os.environ); env["NINFER_PREFILL_MAX_TOKENS"] = ENV_UNIT
    fh = open(os.path.join(WORK, "p3-mtp2-%s.log" % name), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--port", str(PORT)] + flags
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    row = {"config": name, "flags": flags}
    try:
        ready = False
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    ready = True; break
            except Exception:
                pass
        if not ready:
            row["error"] = "engine not ready"; print(json.dumps(row, ensure_ascii=False)); return row
        mid = req("/v1/models")[1]["data"][0]["id"]
        t0 = time.perf_counter()
        st, d = req("/v1/chat/completions", {"model": mid,
                                            "messages": [{"role": "user", "content": PROMPT}],
                                            "max_tokens": MAXTOK, "temperature": 0, "stream": False})
        row["wall_s"] = round(time.perf_counter() - t0, 3)
        row["http"] = st
        ch = (d.get("choices") or [{}])[0]
        text = (ch.get("message") or {}).get("content") or ""
        tm = d.get("timings") or {}
        us = d.get("usage") or {}
        bad, why = garbled(text)
        row.update({"completion_tokens": us.get("completion_tokens"),
                    "decode_tok_s": round(tm.get("predicted_per_second") or 0, 2),
                    "draft_n": tm.get("draft_n"), "draft_accepted": tm.get("draft_n_accepted"),
                    "accept_rate": round((tm.get("draft_n_accepted") or 0) / tm["draft_n"], 3) if tm.get("draft_n") else None,
                    "garbled": bad, "garbled_reason": why,
                    "text_head": text[:110]})
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()
    print(json.dumps(row, ensure_ascii=False))
    sys.stdout.flush()
    return row


rows = [trial(n, f) for n, f in CONFIGS]
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print("saved:", OUT)
