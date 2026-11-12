# p3_trace_probe.py — 定位 MTP prefill trace 的 bad allocation 边界
# 变量：prompt 长度 × --prefill-chunk；判据：dump 文件是否生成 + 引擎是否 500
import json, os, subprocess, sys, time, http.client

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18961

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
        r = c.getresponse()
        return r.status, json.loads(r.read())
    finally:
        c.close()


def one(label, words, chunk, maxtok=8):
    dump = os.path.join(WORK, "trace-probe-%s.bin" % label)
    if os.path.exists(dump):
        os.remove(dump)
    kill_own(); time.sleep(0.4)
    env = dict(os.environ); env["NINFER_TRACE_MTP_PREFILL"] = dump
    fh = open(os.path.join(WORK, "trace-probe.log"), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", str(chunk), "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ok = False
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    ok = True; break
            except Exception:
                pass
        if not ok:
            print("%-18s engine not ready" % label); return
        mid = req("/v1/models")[1]["data"][0]["id"]
        text = " ".join(["word%d" % i for i in range(words)])
        st, d = req("/v1/chat/completions", {"model": mid,
                                            "messages": [{"role": "user", "content": text}],
                                            "max_tokens": maxtok, "temperature": 0})
        pt = (d.get("usage") or {}).get("prompt_tokens")
        size = os.path.getsize(dump) if os.path.exists(dump) else 0
        print("%-18s chunk=%-3d prompt=%-5s status=%s dump=%s"
              % (label, chunk, pt, st, ("%.1fMB" % (size / 1e6)) if size else "NONE"))
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()


one("p20-c16", 20, 16)
one("p60-c16", 60, 16)
one("p60-c32", 60, 32)
one("p60-c128", 60, 128)
one("p200-c128", 200, 128)
one("p200-c32", 200, 32)
