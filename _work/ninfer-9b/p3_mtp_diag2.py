# p3_mtp_diag.py — dump per-round drafts vs target argmax to locate why MTP acceptance is 0
import json
import os
import subprocess
import time
import http.client
from collections import Counter

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18920
DUMP = os.path.join(WORK, "p3-mtp-draft-dump2.txt")
ENGLOG = os.path.join(WORK, "p3-mtp-diag.engine.log")
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


for path in (DUMP, ENGLOG):
    if os.path.exists(path):
        os.remove(path)

kill_own()
env = dict(os.environ)
env["NINFER_DUMP_DRAFT"] = "1"
env["NINFER_TRACE_MTP"] = "1"
env["NINFER_DUMP_DRAFT_FILE"] = DUMP
log = open(ENGLOG, "wb")
proc = subprocess.Popen(
    [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
     "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
     "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT), "--log-level", "info"],
    stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
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
        response = request(PORT, "/v1/chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content": "List five benefits of unit testing."}],
            "max_tokens": 64,
            "temperature": 0,
            "stream": False,
        }, timeout=600)
        if "choices" in response:
            result["text"] = response["choices"][0]["message"].get("content", "")
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

print("timings:", json.dumps(result.get("timings"), ensure_ascii=False))

# Analyse: every round prints  accepted / count / anchor / target tokens / draft tokens
rows = []
if os.path.exists(DUMP):
    with open(DUMP, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("row="):
                continue
            try:
                head, rest = line.split("| draft=", 1)
                fields = dict(part.split("=", 1) for part in head.split() if "=" in part)
                target = [int(x) for x in head.split("target=")[1].split()]
                draft = [int(x) for x in rest.split()]
                rows.append({"extent": int(fields["extent"]), "accepted": int(fields["accepted"]),
                             "count": int(fields["count"]), "anchor": int(fields["anchor"]),
                             "target": target, "draft": draft})
            except Exception:
                continue

print("rounds:", len(rows))
if rows:
    agree0 = sum(1 for r in rows if r["draft"] and r["target"] and r["draft"][0] == r["target"][0])
    print("draft[0] == target[0]:", agree0, "/", len(rows))
    print("accepted distribution:", dict(Counter(r["accepted"] for r in rows)))
    print("first 12 rounds:")
    for r in rows[:12]:
        print("   anchor=%d extent=%d accepted=%d target=%s draft=%s" %
              (r["anchor"], r["extent"], r["accepted"], r["target"][:4], r["draft"][:4]))
    # how often is the draft equal to the token the target produced at the *next* round's anchor?
    same_next = sum(1 for a, b in zip(rows, rows[1:]) if a["draft"] and a["draft"][0] == b["anchor"])
    print("draft[0] == next round anchor:", same_next, "/", max(0, len(rows) - 1))
    with open(os.path.join(WORK, "p3-mtp-diag-result.json"), "w", encoding="utf-8") as f:
        json.dump({"timings": result.get("timings"), "rounds": rows,
                   "agree0": agree0, "same_next": same_next}, f, ensure_ascii=False, indent=2)
print("dump:", DUMP)
