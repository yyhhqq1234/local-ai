# p3_maxtok_probe.py — 验证假设：MTP 在 T=128 的 bad_alloc 是 work arena 与 max_unit_tokens 的交互
# 做法：设 NINFER_PREFILL_MAX_TOKENS=64（引擎支持的 env 覆盖），让 prefill 单元降到 64，再看 trace 是否落盘
import json, os, subprocess, time, http.client

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 18964
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


def trial(label, unit, words, maxtok=8):
    dump = os.path.join(WORK, "maxtok-%s.bin" % label)
    if os.path.exists(dump):
        os.remove(dump)
    kill_own(); time.sleep(0.5)
    env = dict(os.environ)
    env["NINFER_TRACE_MTP_PREFILL"] = dump
    if unit:
        env["NINFER_PREFILL_MAX_TOKENS"] = str(unit)
    fh = open(os.path.join(WORK, "p3-maxtok.log"), "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "2048", "--greedy",
            "--host-context-mib", "1024", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ready = False
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    ready = True; break
            except Exception:
                pass
        if not ready:
            print("%-12s engine not ready (unit=%s)" % (label, unit)); return
        mid = req("/v1/models")[1]["data"][0]["id"]
        text = " ".join("word%d" % i for i in range(words))
        st, d = req("/v1/chat/completions", {"model": mid,
                                            "messages": [{"role": "user", "content": text}],
                                            "max_tokens": maxtok, "temperature": 0})
        size = os.path.getsize(dump) if os.path.exists(dump) else 0
        print("%-12s unit=%-4s prompt=%-5s http=%s dump=%s"
              % (label, unit, (d.get("usage") or {}).get("prompt_tokens"), st,
                 ("%.1fMB" % (size / 1e6)) if size else "NONE"))
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.5); kill_own()


trial("unit64", 64, 120)
trial("unit32", 32, 120)
