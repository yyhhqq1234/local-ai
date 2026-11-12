# p3_matrix_scan.py — verify corrected four-output grouped MMA from T=16 through long prefill
import json
import os
import re
import subprocess
import time
import http.client

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
LIMITS = [15, 16, 20, 24, 32, 64, 128]
BASE_PORT = 1850
CASES = [
    ("u2plus2", [{"role": "user", "content": "What is 2+2?"}], 8),
    ("system", [{"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2?"}], 8),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
    ("long_prefill", [{"role": "user", "content":
                       ("The quick brown fox jumps over the lazy dog. " * 60).strip()}], 8),
    ("long_system", [{"role": "system", "content":
                       ("You are a careful local assistant. Follow the operator's instructions exactly, "
                        "keep answers short, and never invent tool results. ") * 20},
                      {"role": "user", "content": "What is 2+2?"}], 8),
]
PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)
GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own():
    for pid, path in processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def request(port, path, payload=None, timeout=240):
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


def is_garbled(text):
    if not text or "\ufffd" in text:
        return True
    m = GARBAGE.search(text)
    if m:
        s = m.group(0)
        return any(c.islower() for c in s) and any(c.isupper() for c in s)
    return False


def run(limit, port):
    kill_own()
    time.sleep(0.5)
    reqlog = os.path.join(WORK, f"p3-matrix-{limit}.reqlog.jsonl")
    englog = os.path.join(WORK, f"p3-matrix-{limit}.engine.log")
    for pth in (reqlog, englog):
        if os.path.exists(pth):
            os.remove(pth)
    env = dict(os.environ)
    env["NINFER_PREFILL_MAX_TOKENS"] = str(limit)
    log = open(englog, "wb")
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--no-prefix-reuse", "--port", str(port),
            "--request-log-jsonl", reqlog, "--log-level", "trace"]
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    result = {"limit": limit, "ready": False, "cases": []}
    try:
        for _ in range(150):
            time.sleep(0.4)
            if proc.poll() is not None:
                break
            try:
                request(port, "/v1/models", timeout=2)
                result["ready"] = True
                break
            except Exception:
                pass
        if result["ready"]:
            mid = request(port, "/v1/models")["data"][0]["id"]
            for name, messages, max_tokens in CASES:
                started = time.perf_counter()
                try:
                    d = request(port, "/v1/chat/completions",
                                {"model": mid, "messages": messages, "max_tokens": max_tokens,
                                 "temperature": 0, "stream": False})
                    text = d["choices"][0]["message"]["content"] or ""
                    result["cases"].append({"name": name, "chars": len(text),
                                            "garbled": is_garbled(text),
                                            "wall_s": round(time.perf_counter() - started, 3),
                                            "head": " ".join(text.split())[:100]})
                except Exception as e:
                    result["cases"].append({"name": name, "error": repr(e), "garbled": True})
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        log.close()
        time.sleep(0.5)
        kill_own()
    result["all_clean"] = result["ready"] and all(not x.get("garbled", True) for x in result["cases"])
    result["reqlog"] = reqlog
    return result


results = []
for index, limit in enumerate(LIMITS):
    r = run(limit, BASE_PORT + index)
    results.append(r)
    print(json.dumps(r, ensure_ascii=False))
out = os.path.join(WORK, "p3-matrix-scan-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": results, "remaining": processes()}, f, ensure_ascii=False, indent=2)
print("result:", out)
print("remaining:", processes())
