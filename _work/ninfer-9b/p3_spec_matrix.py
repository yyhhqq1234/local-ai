# p3_spec_matrix.py — ⑤ 决策矩阵：同一 prompt/同参数下比较 5 种解码配置
# 目的：找出是否有「零训练」路径能达到 decode ≥100 tok/s（重点测 --spec mtp + --lm-head-draft）
# 纪律：每轮独立起引擎、只杀本 exe 路径、记录 reqlog 与引擎日志尾部
import json
import os
import re
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
PORT = 18930
OUT = os.path.join(WORK, "p3-spec-matrix.json")
LOG = os.path.join(WORK, "p3-spec-matrix.engine.log")

PROMPT = ("Explain why local inference is useful. Give a detailed answer with examples, "
          "at least 200 words.")  # 与 p3_mtp_probe.py 同一 prompt，便于对照
MAX_TOKENS = 256

CONFIGS = [
    ("no-spec", []),
    ("mtp-d3", ["--spec", "mtp", "--draft-tokens", "3"]),
    ("mtp-d1", ["--spec", "mtp", "--draft-tokens", "1"]),
    ("mtp-d1-lmhead", ["--spec", "mtp", "--draft-tokens", "1", "--lm-head-draft"]),
    ("mtp-d3-lmhead", ["--spec", "mtp", "--draft-tokens", "3", "--lm-head-draft"]),
    ("dflash-d3", ["--spec", "dflash", "--draft-tokens", "3"]),
]

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


def req(port, path, payload=None, timeout=600):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        if r.status >= 400:
            return {"http_status": r.status, "body": raw.decode("utf-8", "replace")[:400]}
        return json.loads(raw)
    finally:
        c.close()


def garbled(text):
    if not text.strip():
        return True, "empty"
    if "\ufffd" in text:
        return True, "replacement-char"
    m = re.search(r"[A-Za-z0-9+/]{14,}", text)
    if m and any(c.islower() for c in m.group(0)) and any(c.isupper() for c in m.group(0)):
        return True, "base64-like"
    if re.search(r"(.)\1{6,}", text):
        return True, "char-repeat"
    return False, ""


rows = []
for name, flags in CONFIGS:
    kill_own()
    time.sleep(1.0)
    rlog = os.path.join(WORK, "p3-spec-%s.reqlog.jsonl" % name)
    elog = os.path.join(WORK, "p3-spec-%s.engine.log" % name)
    for p in (rlog, elog):
        if os.path.exists(p):
            os.remove(p)
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--port", str(PORT), "--request-log-jsonl", rlog] + flags
    fh = open(elog, "wb")
    t_start = time.perf_counter()
    proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    row = {"config": name, "flags": flags, "ready": False}
    try:
        for _ in range(240):
            time.sleep(0.5)
            if proc.poll() is not None:
                row["died"] = True
                break
            try:
                m = req(PORT, "/v1/models", timeout=2)
                if isinstance(m, dict) and "data" in m:
                    row["ready"] = True
                    row["startup_s"] = round(time.perf_counter() - t_start, 2)
                    break
            except Exception:
                pass
        if row["ready"]:
            mid = req(PORT, "/v1/models")["data"][0]["id"]
            t0 = time.perf_counter()
            resp = req(PORT, "/v1/chat/completions", {
                "model": mid,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": MAX_TOKENS, "temperature": 0, "stream": False}, timeout=600)
            row["wall_s"] = round(time.perf_counter() - t0, 3)
            if "choices" in resp:
                text = resp["choices"][0]["message"].get("content") or ""
                row["chars"] = len(text)
                row["finish"] = resp["choices"][0].get("finish_reason")
                row["usage"] = resp.get("usage")
                row["timings"] = resp.get("timings")
                bad, why = garbled(text)
                row["garbled"] = bad
                row["garbled_reason"] = why
                row["text_head"] = text[:180]
                ct = (resp.get("usage") or {}).get("completion_tokens") or 0
                dec = (resp.get("timings") or {}).get("decode") or 0
                row["decode_tok_s"] = round(ct / dec, 2) if dec else None
            else:
                row["error"] = resp
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        fh.close()
        time.sleep(0.5)
        kill_own()
    # reqlog 里的投机统计
    if os.path.exists(rlog):
        stats = []
        with open(rlog, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("event") == "request_done":
                    stats.append({k: d.get(k) for k in
                                  ("draft_n_accepted", "draft_n", "speculative", "result", "timings_seconds")})
        row["reqlog_tail"] = stats[-1:] if stats else []
    if os.path.exists(elog):
        with open(elog, encoding="utf-8", errors="replace") as f:
            tail = [l.rstrip() for l in f if l.strip()][-6:]
        row["engine_log_tail"] = tail
    rows.append(row)
    print(json.dumps({k: v for k, v in row.items()
                      if k in ("config", "ready", "startup_s", "wall_s", "usage", "timings",
                               "decode_tok_s", "garbled", "garbled_reason", "draft_n_accepted",
                               "reqlog_tail", "error", "died")}, ensure_ascii=False))
    sys.stdout.flush()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"prompt": PROMPT, "max_tokens": MAX_TOKENS, "rows": rows}, f,
              ensure_ascii=False, indent=2)
print("saved:", OUT)
print("remaining:", processes())
