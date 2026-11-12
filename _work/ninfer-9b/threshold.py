# threshold.py — 找"提示词长度 → 退化"的翻转点（自起引擎，自收口）
import json, os, subprocess, sys, time, urllib.request
from jinja2 import Environment
from tokenizers import Tokenizer

ROOT  = r"D:\BaiduNetdiskDownload\Local-AI"
EXE   = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
TPL   = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\chat_template.jinja")
TOK   = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\tokenizer.json")
PORT  = 1634
BASE  = "What is 2+2?"

tpl = open(TPL, encoding="utf-8").read()
tok = Tokenizer.from_file(TOK)
env = Environment(trim_blocks=False, lstrip_blocks=False)

def count(text):
    s = env.from_string(tpl).render(messages=[{"role":"user","content":text}], add_generation_prompt=True,
        bos_token="", eos_token="", enable_thinking=False, reasoning_effort="none")
    return len(tok.encode(s, add_special_tokens=False).ids)

def pad_to(target):
    text = BASE
    pad = [" (", "please", " answer", " directly", " now", " thanks", " ok", " fine"]
    i = 0
    while count(text) < target:
        text += pad[i % len(pad)]
        i += 1
        if i > 200: break
    return text

# 起引擎
subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
time.sleep(0.8)
log = open(os.path.join(ROOT, r"_work\ninfer-9b\threshold-engine.log"), "wb")
proc = subprocess.Popen([EXE, MODEL, "--max-context","4096","--greedy","--host-context-mib","2048",
                         "--prefill-chunk","128","--no-thinking","--port",str(PORT)],
                        stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
def get(url):
    with urllib.request.urlopen(url, timeout=3) as r: return json.loads(r.read())
ready = False
for _ in range(240):
    time.sleep(0.5)
    if proc.poll() is not None: break
    try: get(f"http://127.0.0.1:{PORT}/v1/models"); ready = True; break
    except Exception: pass
if not ready:
    print("ENGINE NOT READY"); proc.kill(); sys.exit(2)
mid = get(f"http://127.0.0.1:{PORT}/v1/models")["data"][0]["id"]

def chat(text, mt=32):
    body = json.dumps({"model":mid,"messages":[{"role":"user","content":text}],
                       "max_tokens":mt,"temperature":0,"stream":False}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"]["content"], d["usage"]["completion_tokens"]

print("target  actual  reply")
for target in (22, 23, 24, 25, 26, 27):
    p = pad_to(target)
    try:
        txt, ctok = chat(p)
    except Exception as e:
        print(f"  {target}  ERR {e}"); continue
    head = " ".join(txt.split())[:80]
    print(f"  {target:3d}     {count(p):3d}   {head}")

proc.kill()
time.sleep(0.5)
subprocess.run(["taskkill","/F","/IM","ninfer-serve.exe"], capture_output=True)
print("engine stopped")
