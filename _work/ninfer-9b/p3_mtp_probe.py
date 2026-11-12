# p3_mtp_probe.py — measure current GSQ MTP speculative decoding after the local projection fix
import json
import os
import subprocess
import time
import http.client

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18910
REQLOG = os.path.join(WORK, "p3-mtp-probe.reqlog.jsonl")
ENGINELOG = os.path.join(WORK, "p3-mtp-probe.engine.log")
PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own():
    for pid, path in processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def request(port, path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        response = c.getresponse()
        raw = response.read()
        if response.status >= 400:
            return {"http_status": response.status, "body": raw.decode("utf-8", "replace")}
        return json.loads(raw)
    finally:
        c.close()


for path in (REQLOG, ENGINELOG):
    if os.path.exists(path):
        os.remove(path)
kill_own()
log = open(ENGINELOG, "wb")
proc = subprocess.Popen(
    [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
     "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
     "--spec", "mtp", "--draft-tokens", "3", "--port", str(PORT),
     "--request-log-jsonl", REQLOG, "--log-level", "info"],
    stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
result = {"ready": False}
try:
    for _ in range(240):
        time.sleep(0.5)
        if proc.poll() is not None:
            break
        try:
            models = request(PORT, "/v1/models", timeout=2)
            if isinstance(models, dict) and "data" in models:
                result["ready"] = True
                break
        except Exception:
            pass
    print("ready:", result["ready"])
    if result["ready"]:
        model_id = request(PORT, "/v1/models")["data"][0]["id"]
        started = time.perf_counter()
        response = request(PORT, "/v1/chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content":
                          "Explain why local inference is useful. Give a detailed answer with examples."}],
            "max_tokens": 192,
            "temperature": 0,
            "stream": False,
        }, timeout=600)
        result["wall_s"] = round(time.perf_counter() - started, 3)
        if "choices" in response:
            message = response["choices"][0]["message"]
            result["text"] = message.get("content", "")
            result["chars"] = len(result["text"])
            result["finish_reason"] = response["choices"][0].get("finish_reason")
            result["usage"] = response.get("usage")
            result["timings"] = response.get("timings")
        else:
            result["error"] = response
finally:
    try:
        proc.kill()
    except Exception:
        pass
    log.close()
    time.sleep(0.5)
    kill_own()

if os.path.exists(REQLOG):
    with open(REQLOG, encoding="utf-8") as f:
        result["reqlog"] = [json.loads(line) for line in f if line.strip()]
with open(os.path.join(WORK, "p3-mtp-probe-result.json"), "w", encoding="utf-8") as f:
    json.dump({"result": result, "remaining": processes()}, f, ensure_ascii=False, indent=2)
print("result:", json.dumps({k: v for k, v in result.items() if k not in ("text", "reqlog")},
                              ensure_ascii=False))
print("remaining:", processes())
