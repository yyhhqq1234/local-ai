# flags.py — 同一失败请求在不同引擎开关下复测，定位数值路径
import json, os, subprocess, sys, time, http.client
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

ROOT  = r"D:\BaiduNetdiskDownload\Local-AI"
EXE   = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
PORT  = 1637

PROMPT = "Write a 300-word essay about why local inference matters."

VARIANTS = [
 ("baseline",              []),
 ("no-cuda-graph",         ["--no-cuda-graph"]),
 ("no-prefill-a8",         ["--no-prefill-a8"]),
 ("no-prefill-cublas-proj",["--no-prefill-cublas-projections"]),
 ("chunk256",              ["--prefill-chunk","256"]),
 ("kv-int8",               ["--kv-dtype","int8"]),
 ("no-prefix-reuse",       ["--no-prefix-reuse"]),
 ("gdn-state-fp16",        ["--gdn-state-fp16"]),
]

def http_json(path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None: c.request("GET", path)
        else: c.request("POST", path, body=json.dumps(payload).encode(),
                        headers={"Content-Type":"application/json"})
        return json.loads(c.getresponse().read())
    finally: c.close()

def run(name, extra):
    subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
    time.sleep(0.8)
    args = [EXE, MODEL, "--max-context","4096","--greedy","--host-context-mib","2048",
            "--no-thinking","--port",str(PORT)] + extra
    if "--prefill-chunk" not in extra: args += ["--prefill-chunk","128"]
    logp = os.path.join(ROOT, r"_work\infer-9b" if False else r"_work\ninfer-9b", f"flag-{name}.log")
    log = open(logp, "wb")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    ok=False; last=None
    for _ in range(120):
        time.sleep(0.5)
        if p.poll() is not None: last=f"exit {p.poll()}"; break
        try: http_json("/v1/models", timeout=2); ok=True; break
        except Exception as e: last=repr(e)
    if not ok:
        print(f"[{name}] NOT READY {last}"); p.kill(); return
    mid = http_json("/v1/models")["data"][0]["id"]
    try:
        d = http_json("/v1/chat/completions", {"model":mid,"messages":[{"role":"user","content":PROMPT}],
                                               "max_tokens":32,"temperature":0,"stream":False})
        txt = d["choices"][0]["message"]["content"]
        print(f"[{name}] chars={len(txt)} >>> {' '.join(txt.split())[:95]}")
    except Exception as e:
        print(f"[{name}] REQ ERR {e}")
    p.kill(); time.sleep(0.4)

for name, extra in VARIANTS:
    run(name, extra)
subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
print("all stopped")
