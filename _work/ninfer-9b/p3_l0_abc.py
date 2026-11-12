# p3_l0_abc.py — L0 单变量实验：分离 P1(capture 路径) / P2(短窗口 kernel)
# 纪律：只按 Path 杀本档位引擎 _tools\ninfer-build\apps\ninfer-serve.exe；
#       绝不按进程名杀，避免误伤 27B csunx 档位（AGENTS.md 三绑定约束）。
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

PROMPTS = [
    ("user", [{"role": "user", "content": "What is 2+2?"}], 16),
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}], 16),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
]

VARIANTS = [
    ("a-baseline", ["--host-context-mib", "2048"], 1641),
    ("b-no-prefix-reuse", ["--host-context-mib", "2048", "--no-prefix-reuse"], 1642),
    ("c-slots0-host0", ["--host-context-mib", "0", "--device-state-slots", "0"], 1643),
    ("d-slots0-host2048", ["--host-context-mib", "2048", "--device-state-slots", "0"], 1644),
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
            f_out = d.get("first_output_timing", {})
            state = f_out.get("context_transfers", {}).get("state", {})
            rows.append({
                "prompt_tokens": r.get("prompt_tokens"),
                "computed_prefill_tokens": f_out.get("computed_prefill_tokens"),
                "prefix_cache_hit_tokens": r.get("prefix_cache_hit_tokens"),
                "prefix_reuse_path": r.get("prefix_reuse_path"),
                "completion_tokens": r.get("completion_tokens"),
                "ids_head": (r.get("generated_token_ids") or [])[:8],
                "state_d2h_bytes": state.get("d2h", {}).get("bytes"),
                "state_d2d_bytes": state.get("d2d", {}).get("bytes"),
                "units_prefill": d.get("engine_timing", {}).get("units", {}).get("prefill"),
                "prefill_seconds": d.get("timings_seconds", {}).get("prefill"),
                "sched_d2h": d.get("generation", {}).get("scheduling", {}).get("device_to_host_bytes"),
            })
    return rows


def run(name, extra, port):
    kill_own_engine()
    time.sleep(0.8)
    reqlog = os.path.join(WORK, "l0-%s.reqlog.jsonl" % name)
    englog = os.path.join(WORK, "l0-%s.engine.log" % name)
    if os.path.exists(reqlog):
        os.remove(reqlog)
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--prefill-chunk", "128",
            "--no-thinking", "--port", str(port), "--request-log-jsonl", reqlog,
            "--log-level", "trace"] + extra
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
        texts = []
        for label, msgs, mt in PROMPTS:
            try:
                d = http_json(port, "/v1/chat/completions",
                              {"model": mid, "messages": msgs, "max_tokens": mt,
                               "temperature": 0, "stream": False})
                t = d["choices"][0]["message"]["content"]
                texts.append({"label": label, "chars": len(t),
                              "head": " ".join(t.split())[:95]})
            except Exception as e:
                texts.append({"label": label, "error": repr(e)})
        result["requests"] = texts
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
for name, extra, port in VARIANTS:
    r = run(name, extra, port)
    all_results.append(r)
    print("[%s] ready=%s error=%s" % (name, r["ready"], r.get("error", "")))
    for t in r["requests"]:
        print("   %-6s chars=%s >>> %s" % (t["label"], t.get("chars"), t.get("head") or t.get("error")))
    for q in r.get("reqlog", []):
        print("   req: prompt=%s hit=%s path=%s d2h=%s units=%s ids=%s" %
              (q["prompt_tokens"], q["prefix_cache_hit_tokens"], q["prefix_reuse_path"],
               q["state_d2h_bytes"], q["units_prefill"], q["ids_head"]))

kill_own_engine()
time.sleep(0.5)
remain = ninfer_processes()
out = os.path.join(WORK, "l0-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_results, "remaining_ninfer_processes": remain}, f,
              ensure_ascii=False, indent=2)
print("remaining ninfer processes:", remain)
print("result json:", out)
