# p3_l0b_sys.py — L0b：在 --no-prefix-reuse 干净基线上穷举 0 编译解法，针对 system 失败例
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
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")

SYS = [{"role": "system", "content": "You are a helpful assistant."},
       {"role": "user", "content": "What is 2+2?"}]
FORMS = [
    ("sys", SYS, 16),
    ("sys-short", [{"role": "system", "content": "OK."},
                   {"role": "user", "content": "What is 2+2?"}], 16),
    ("user-prefix", [{"role": "user",
                      "content": "You are a helpful assistant.\n\nWhat is 2+2?"}], 16),
    ("user-long", [{"role": "user",
                    "content": "Please answer the following short arithmetic question clearly and briefly: what is 2+2?"}], 16),
]

BASE = ["--host-context-mib", "2048", "--prefill-chunk", "128",
        "--max-context", "4096", "--no-prefix-reuse"]

VARIANTS = [
    ("b0-baseline", BASE, 1651, FORMS),
    ("b1-chunk256", ["--host-context-mib", "2048", "--prefill-chunk", "256",
                     "--max-context", "4096", "--no-prefix-reuse"], 1652, [FORMS[0]]),
    ("b2-ctx16384", ["--host-context-mib", "2048", "--prefill-chunk", "128",
                     "--max-context", "16384", "--no-prefix-reuse"], 1653, [FORMS[0]]),
    ("b3-no-cuda-graph", BASE + ["--no-cuda-graph"], 1654, [FORMS[0]]),
    ("b4-chunk256-nocuda", ["--host-context-mib", "2048", "--prefill-chunk", "256",
                            "--max-context", "4096", "--no-prefix-reuse",
                            "--no-cuda-graph"], 1655, [FORMS[0]]),
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
            state = d.get("first_output_timing", {}).get("context_transfers", {}).get("state", {})
            rows.append({
                "prompt_tokens": r.get("prompt_tokens"),
                "prefix_cache_hit_tokens": r.get("prefix_cache_hit_tokens"),
                "state_d2h_bytes": state.get("d2h", {}).get("bytes"),
                "units_prefill": d.get("engine_timing", {}).get("units", {}).get("prefill"),
                "ids_head": (r.get("generated_token_ids") or [])[:8],
            })
    return rows


def run(name, extra, port, forms):
    kill_own_engine()
    time.sleep(0.8)
    reqlog = os.path.join(WORK, "l0b-%s.reqlog.jsonl" % name)
    englog = os.path.join(WORK, "l0b-%s.engine.log" % name)
    if os.path.exists(reqlog):
        os.remove(reqlog)
    args = [EXE, MODEL, "--greedy", "--no-thinking", "--port", str(port),
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
                t = d["choices"][0]["message"]["content"]
                result["requests"].append({"label": label, "chars": len(t),
                                           "head": " ".join(t.split())[:95]})
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
        print("   %-12s chars=%s >>> %s" % (t["label"], t.get("chars"), t.get("head") or t.get("error")))
    for q in r.get("reqlog", []):
        print("   req: prompt=%s hit=%s d2h=%s units=%s ids=%s" %
              (q["prompt_tokens"], q["prefix_cache_hit_tokens"], q["state_d2h_bytes"],
               q["units_prefill"], q["ids_head"]))

kill_own_engine()
time.sleep(0.5)
remain = ninfer_processes()
out = os.path.join(WORK, "l0b-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_results, "remaining_ninfer_processes": remain}, f,
              ensure_ascii=False, indent=2)
print("remaining ninfer processes:", remain)
print("result json:", out)
