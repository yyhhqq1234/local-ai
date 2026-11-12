# p3_regress_llamaserver.py — 17 例回归（llama-server / OpenAI 端点）
import json
import os
import re
import statistics
import http.client

PORT = 8080
MODEL = os.environ.get("MODEL", r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\gguf\kittyrev9b-Q5_K_M-im.gguf")

SETS = [
    ("p1-2+2", "What is 2+2?", 32, "4"),
    ("p2-hello", "Say hello in Chinese.", 24, "你好"),
    ("p3-gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
    ("p4-pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
    ("p5-unittest", "List 3 benefits of unit testing.", 128, "test"),
]
GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def chat(prompt, n, system=None):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    body = {"model": MODEL, "messages": msgs, "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=900)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    t = d.get("timings") or {}
    return (((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "",
            t.get("predicted_per_second") or 0)


def bad(t):
    if not t.strip():
        return "empty"
    if "\ufffd" in t:
        return "replacement-char"
    m = GARBAGE.search(t)
    if m and any(ch.islower() for ch in m.group(0)) and any(ch.isupper() for ch in m.group(0)):
        return "base64-like"
    if re.search(r"(.)\1{6,}", t):
        return "char-repeat"
    return ""


rows, tok = [], []
for name, prompt, n, kw in SETS:
    for rep in range(1, 4):
        text, sp = chat(prompt, n)
        b = bad(text)
        ok = (not b) and kw.lower() in text.lower()
        rows.append({"case": "%s-r%d" % (name, rep), "ok": ok, "bad": b, "chars": len(text),
                     "tok_s": round(sp, 2), "head": text[:70].replace("\n", " ")})
        if sp:
            tok.append(sp)
text, sp = chat("What is 2+2?", 16, system="You are a helpful assistant.")
b = bad(text); ok = (not b) and "4" in text
rows.append({"case": "sys", "ok": ok, "bad": b, "chars": len(text), "tok_s": round(sp, 2),
             "head": text[:70].replace("\n", " ")})
if sp:
    tok.append(sp)
text, sp = chat("Write a 300-word essay about why local inference matters.", 24)
rows.append({"case": "essay", "ok": (not bad(text)), "bad": bad(text), "chars": len(text),
             "tok_s": round(sp, 2), "head": text[:70].replace("\n", " ")})
if sp:
    tok.append(sp)

ok_n = sum(1 for r in rows if r["ok"])
print(json.dumps({"model": os.path.basename(MODEL), "ok": ok_n, "total": len(rows),
                  "bad_markers": [r["case"] for r in rows if r["bad"]],
                  "tok_s_median": round(statistics.median(tok), 2) if tok else 0,
                  "tok_s_min": round(min(tok), 2) if tok else 0,
                  "tok_s_max": round(max(tok), 2) if tok else 0}, ensure_ascii=False))
for r in rows:
    print("%-12s ok=%-5s %-14s %6.2f t/s %4d chars | %s" %
          (r["case"], r["ok"], r["bad"] or "-", r["tok_s"], r["chars"], r["head"]))
