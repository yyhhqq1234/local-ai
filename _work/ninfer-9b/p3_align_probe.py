# p3_align_probe.py — 标定 decode 域 hidden ↔ 生成 token 的对齐（用 NINFER_DUMP_DRAFT 的 anchor）
import json
import os
import subprocess
import sys
import time
import http.client
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.environ.get("MTP_MODEL", os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-mtp2f-GSQ.ninfer"))
BASE = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18998
W = 4096
PS = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
      "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def kill_own():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].strip().lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", p[0].strip(), "/F"], capture_output=True)


def req(path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse(); raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def run(maxtok):
    tag = "m%d" % maxtok
    ar = os.path.join(BASE, "align-%s-ar.bin" % tag)
    dr = os.path.join(BASE, "align-%s-draft.txt" % tag)
    rl = os.path.join(BASE, "align-%s-req.jsonl" % tag)
    for p in (ar, dr, rl):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env.update({"NINFER_TRACE_AR": ar, "NINFER_DUMP_DRAFT": "1", "NINFER_DUMP_DRAFT_FILE": dr,
                "NINFER_PREFILL_MAX_TOKENS": "64"})
    kill_own(); time.sleep(0.5)
    fh = open(os.path.join(BASE, "align.log"), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT),
            "--request-log-jsonl", rl]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                print("engine died"); return None
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    break
            except Exception:
                pass
        mid = req("/v1/models")[1]["data"][0]["id"]
        st, d = req("/v1/chat/completions", {"model": mid, "max_tokens": maxtok, "temperature": 0,
                                            "messages": [{"role": "user", "content": "List three benefits of unit testing."}]})
        us = d.get("usage") or {}
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()

    recs = (os.path.getsize(ar) // (W * 2)) if os.path.exists(ar) else 0
    ids = []
    if os.path.exists(rl):
        for line in open(rl, encoding="utf-8"):
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("event") == "request_done":
                ids = (j.get("result") or {}).get("generated_token_ids") or []
    drafts = []
    if os.path.exists(dr):
        for line in open(dr, encoding="utf-8"):
            drafts.append(line.strip())
    return {"maxtok": maxtok, "prompt_tokens": us.get("prompt_tokens"),
            "completion": us.get("completion_tokens"), "recs": recs,
            "gen_ids": len(ids), "draft_lines": len(drafts),
            "ids_head": ids[:6], "draft_head": drafts[:3], "draft_tail": drafts[-2:]}


for mt in (8, 16, 32, 64):
    r = run(mt)
    print(json.dumps(r, ensure_ascii=False))
