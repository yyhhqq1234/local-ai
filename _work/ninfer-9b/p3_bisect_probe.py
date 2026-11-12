# bisect.py — 逐项拆解退化触发点（essay 词 vs system 角色）
import json, os, subprocess, sys, time
try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception: pass

ROOT  = r"D:\BaiduNetdiskDownload\Local-AI"
EXE   = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.environ.get("MODEL") or os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
PORT  = int(os.environ.get("PORT") or 1635)

subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
time.sleep(0.8)
log = open(os.path.join(ROOT, r"_work\ninfer-9b\bisect-engine.log"), "wb")
proc = subprocess.Popen([EXE, MODEL, "--max-context","4096","--greedy","--host-context-mib","2048",
                         "--prefill-chunk","128","--no-thinking","--port",str(PORT)] + (os.environ.get("EXTRA","").split() if os.environ.get("EXTRA") else []),
                        stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
import http.client

def http_json(path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return json.loads(r.read())
    finally:
        c.close()

ready = False
last = None
for i in range(240):
    time.sleep(0.5)
    if proc.poll() is not None:
        last = f"engine exited code={proc.poll()}"; break
    try:
        http_json("/v1/models", timeout=2); ready = True; break
    except Exception as e:
        last = repr(e)
if not ready:
    print("NOT READY:", last); proc.kill(); sys.exit(2)
mid = http_json("/v1/models")["data"][0]["id"]

def chat(msgs, mt=32):
    d = http_json("/v1/chat/completions", {"model":mid,"messages":msgs,"max_tokens":mt,
                                           "temperature":0,"stream":False})
    return d["choices"][0]["message"]["content"], d["usage"]["prompt_tokens"]

U = lambda t: [{"role":"user","content":t}]
S = lambda s,t: [{"role":"system","content":s},{"role":"user","content":t}]

cases = [
 ("1 essay-orig",        U("Write a 300-word essay about why local inference matters.")),
 ("2 essay-cats",        U("Write a 300-word essay about cats.")),
 ("3 essay-short",       U("Write an essay about why local inference matters.")),
 ("4 essay+noconstraint",U("Write a 300-word essay about why local inference matters. Be concise.")),
 ("5 essay-fragment",    U("Essay about local inference matters.")),
 ("6 300word-essay",     U("Write a 300-word essay.")),
 ("7 localinference",    U("Why does local inference matter?")),
 ("8 sys-hi",            S("hi","What is 2+2?")),
 ("9 sys-empty",         S("","What is 2+2?")),
 ("10 sys-zh",           S("你是助手。","What is 2+2?")),
]
for name, msgs in cases:
    try:
        txt, pt = chat(msgs)
    except Exception as e:
        print(f"[{name}] ERR {e}"); continue
    head = "".join((" " if c.isspace() else c) for c in txt)[:85]
    print(f"[{name}] pt={pt} chars={len(txt)}\n     >>> {head}")

proc.kill(); time.sleep(0.5)
subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
print("engine stopped")
