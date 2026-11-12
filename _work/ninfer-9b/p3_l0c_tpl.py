# p3_l0c_tpl.py — L0c：最后两个 0 编译方向（换 chat 模板 / 换量化产物）
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
GSQ = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
Q4Q5 = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\oxcoder-9b-Q4Q5.ninfer")
MIN_TPL = os.path.join(WORK, "min-qwen.jinja")

PROMPTS = [
    ("user", [{"role": "user", "content": "What is 2+2?"}], 16),
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}], 16),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}], 24),
]

BASE = ["--host-context-mib", "2048", "--prefill-chunk", "128",
        "--max-context", "4096", "--no-prefix-reuse"]

VARIANTS = [
    ("c0-gsq-orig-tpl", GSQ, BASE, 1661),
    ("c1-gsq-min-tpl", GSQ, BASE + ["--chat-template", MIN_TPL], 1662),
    ("c2-q4q5-orig-tpl", Q4Q5, BASE, 1663),
    ("c3-q4q5-min-tpl", Q4Q5, BASE + ["--chat-template", MIN_TPL], 1664),
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


def run(name, model, extra, port):
    kill_own_engine()
    time.sleep(0.8)
    reqlog = os.path.join(WORK, "l0c-%s.reqlog.jsonl" % name)
    englog = os.path.join(WORK, "l0c-%s.engine.log" % name)
    if os.path.exists(reqlog):
        os.remove(reqlog)
    args = [EXE, model, "--greedy", "--no-thinking", "--port", str(port),
            "--request-log-jsonl", reqlog, "--log-level", "info"] + extra
    log = open(englog, "wb")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    result = {"variant": name, "model": os.path.basename(model), "extra": extra,
              "port": port, "ready": False, "requests": []}
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
        for label, msgs, mt in PROMPTS:
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


print("min template exists:", os.path.exists(MIN_TPL))
print("Q4Q5 artifact exists:", os.path.exists(Q4Q5))
all_results = []
for name, model, extra, port in VARIANTS:
    r = run(name, model, extra, port)
    all_results.append(r)
    print("[%s] ready=%s error=%s" % (name, r["ready"], r.get("error", "")))
    for t in r["requests"]:
        print("   %-6s chars=%s >>> %s" % (t["label"], t.get("chars"), t.get("head") or t.get("error")))
    for q in r.get("reqlog", []):
        print("   req: prompt=%s hit=%s d2h=%s units=%s ids=%s" %
              (q["prompt_tokens"], q["prefix_cache_hit_tokens"], q["state_d2h_bytes"],
               q["units_prefill"], q["ids_head"]))

kill_own_engine()
time.sleep(0.5)
remain = ninfer_processes()
out = os.path.join(WORK, "l0c-result.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"results": all_results, "remaining_ninfer_processes": remain}, f,
              ensure_ascii=False, indent=2)
print("remaining ninfer processes:", remain)
print("result json:", out)
