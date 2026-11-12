# p3_len_scan.py — 本地数值定位：固定模板，逐步加长同一问题，找 prompt 长度分档边界
# 若某个 token 数突然从正常转乱码，即可指向 select_*_k4096 的 tokens 分档 kernel。
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
PORT = 1701
REQ = os.path.join(WORK, "p3-len.reqlog.jsonl")
ENG = os.path.join(WORK, "p3-len.engine.log")

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


def parse_reqlog():
    rows = []
    if not os.path.exists(REQ):
        return rows
    with open(REQ, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "request_done":
                continue
            r = d.get("result", {})
            rows.append({
                "prompt_tokens": r.get("prompt_tokens"),
                "units": d.get("engine_timing", {}).get("units", {}).get("prefill"),
                "ids": (r.get("generated_token_ids") or [])[:6],
            })
    return rows


def main():
    kill_own_engine()
    time.sleep(0.7)
    for p in (REQ, ENG):
        if os.path.exists(p):
            os.remove(p)
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse",
            "--port", str(PORT), "--request-log-jsonl", REQ, "--log-level", "info"]
    f = open(ENG, "wb")
    p = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    results = []
    try:
        ready = False
        for _ in range(120):
            time.sleep(0.4)
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
            return
        mid = http_json(PORT, "/v1/models")["data"][0]["id"]
        for k in range(0, 15):
            content = ("context " * k) + "What is 2+2?"
            try:
                d = http_json(PORT, "/v1/chat/completions",
                              {"model": mid, "messages": [{"role": "user", "content": content}],
                               "max_tokens": 8, "temperature": 0, "stream": False})
                t = d["choices"][0]["message"]["content"] or ""
                results.append({"k": k, "text": " ".join(t.split())[:80],
                                "has4": "4" in t})
            except Exception as e:
                results.append({"k": k, "text": "ERR " + repr(e), "has4": False})
        time.sleep(0.5)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        f.close()
        time.sleep(0.4)
        kill_own_engine()

    rows = parse_reqlog()
    print("=== length scan (%d requests) ===" % len(results))
    for i, x in enumerate(results):
        q = rows[i] if i < len(rows) else {}
        print("  k=%-2d prompt=%-3s units=%-3s has4=%-5s ids=%-28s >>> %s" %
              (x["k"], q.get("prompt_tokens"), q.get("units"), x["has4"],
               str(q.get("ids")), x["text"]))
    bad = [i for i, x in enumerate(results) if not x["has4"]]
    print("=== first bad k = %s === " % (bad[0] if bad else "NONE"))
    print("=== remaining: %s ===" % ninfer_processes())
    out = os.path.join(WORK, "p3-len-result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"results": results, "reqlog": rows, "remaining": ninfer_processes()},
                  f, ensure_ascii=False, indent=2)
    print("result:", out)


if __name__ == "__main__":
    main()
