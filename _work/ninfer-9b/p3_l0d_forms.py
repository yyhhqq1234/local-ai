# p3_l0d_forms.py — L0d：验证「不依赖最小模板」能否修好 system（路径甲可行性）
# 纪律：只按 Path 杀本档位引擎；绝不按名杀。
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
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
Q4Q5 = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\oxcoder-9b-Q4Q5.ninfer")

FORMS = [
    ("user", [{"role": "user", "content": "What is 2+2?"}], 16),
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}], 16),
    ("user-prefix", [{"role": "user",
                      "content": "You are a helpful assistant.\n\nWhat is 2+2?"}], 16),
    ("sys-short", [{"role": "system", "content": "OK."},
                   {"role": "user", "content": "What is 2+2?"}], 16),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
]

BASE = ["--host-context-mib", "2048", "--prefill-chunk", "128",
        "--max-context", "4096", "--no-prefix-reuse"]

VARIANTS = [
    ("d0-q4q5-nothink", BASE + ["--no-thinking"], 1671, FORMS),
    ("d1-q4q5-think", BASE, 1672, [FORMS[0], FORMS[1]]),
]

PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def ninfer_processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            out.append((int(parts[0].strip()), parts[1].strip()))
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


def parse_reqlog(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
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
                "units_prefill": d.get("engine_timing", {}).get("units", {}).get("prefill"),
                "ids_head": (r.get("generated_token_ids") or [])[:8],
            })
    return rows


def run(name, extra, port, forms):
    kill_own_engine()
    time.sleep(0.8)
    reqlog = os.path.join(WORK, "l0d-%s.reqlog.jsonl" % name)
    englog = os.path.join(WORK, "l0d-%s.engine.log" % name)
    if os.path.exists(reqlog):
        os.remove(reqlog)
    args = [EXE, Q4Q5, "--greedy", "--port", str(port),
            "--request-log-jsonl", reqlog, "--log-level", "info"] + extra
    log = open(englog, "wb")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    result = {"variant": name, "extra": extra, "port": port, "ready": False, "requests": []}
    try:
        ready = False
        last = None
        for _ in range(160):
            time.sleep(0.5)
            if p.poll() is not None:
                last = "exit %s" % p.poll()
                break
            try:
                http_json(port, "/v1/models", timeout=2)
                ready = True
                break
            except Exception as e:
                last = repr(e)
        if not ready:
            result["error"] = "NOT READY " + str(last)
            with open(englog, "rb") as f:
                result["log_tail"] = f.read()[-1500:].decode("utf-8", "replace")
            return result
        result["ready"] = True
        mid = http_json(port, "/v1/models")["data"][0]["id"]
        for label, msgs, mt in forms:
            try:
                d = http_json(port, "/v1/chat/completions",
                              {"model": mid, "messages": msgs, "max_tokens": mt,
                               "temperature": 0, "stream": False})
                msg = d["choices"][0]["message"]
                t = msg.get("content") or ""
                reason = msg.get("reasoning_content") or ""
                result["requests"].append({"label": label, "chars": len(t),
                                           "head": " ".join(t.split())[:95],
                                           "reason_chars": len(reason),
                                           "reason_head": " ".join(reason.split())[:60]})
            except Exception as e:
                result["requests"].append({"label": label, "error": repr(e)})
        time.sleep(0.6)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        log.close()
        time.sleep(0.5)
        kill_own_engine()
    result["reqlog"] = parse_reqlog(reqlog)
    return result


all_results = []
for name, extra, port, forms in VARIANTS:
    r = run(name, extra, port, forms)
    all_results.append(r)
    print("[%s] ready=%s error=%s" % (name, r["ready"], r.get("error", "")))
    for t in r["requests"]:
        print("   %-12s chars=%s >>> %s | reason=%s %s" %
              (t["label"], t.get("chars"), t.get("head") or t.get("error"),
               t.get("reason_chars"), t.get("reason_head")))
    for q in r.get("reqlog", []):
        print("   req: prompt=%s units=%s ids=%s" %
              (q["prompt_tokens"], q["units_prefill"], q["ids_head"]))

kill_own_engine()
time.sleep(0.5)
remain = ninfer_processes()
out = os.path.join(WORK, "l0d-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_results, "remaining_ninfer_processes": remain}, f,
              ensure_ascii=False, indent=2)
print("remaining ninfer processes:", remain)
print("result json:", out)
