# p3_regress_ollama.py — 用同一套 17 例回归（引擎版 p3_regress.py 的 prompt/判据）打 Ollama 端点
import json
import os
import re
import statistics
import http.client

MODEL = os.environ.get("MODEL", "kittyrev9b-q4km")
PORT = 8080

SETS = [
    ("p1-2+2", "What is 2+2?", 32, "4"),
    ("p2-hello", "Say hello in Chinese.", 24, "你好"),
    ("p3-gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
    ("p4-pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
    ("p5-unittest", "List 3 benefits of unit testing.", 128, "test"),
]
EXTRA = [
    ("sys", "You are a helpful assistant.\n\nWhat is 2+2?", 16, "4"),
    ("essay", "Write a 300-word essay about why local inference matters.", 24, None),
]
GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def gen(prompt, n, system=None, repeat=1, greedy=True):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
        prompt = prompt
        msgs.append({"role": "user", "content": prompt})
    body = {"model": MODEL, "stream": False,
            "options": {"num_predict": n, "temperature": 0 if greedy else 0.7, "num_ctx": 4096}}
    if msgs:
        body["messages"] = msgs
    else:
        body["prompt"] = prompt
    outs = []
    for _ in range(repeat):
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=900)
        c.request("POST", "/api/generate" if "prompt" in body else "/api/chat",
                  body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        r = c.getresponse(); d = json.loads(r.read()); c.close()
        text = d.get("response") or (d.get("message") or {}).get("content") or ""
        ec, ed = d.get("eval_count") or 0, d.get("eval_duration") or 1
        outs.append({"text": text, "tok_s": ec / (ed / 1e9)})
    return outs


def looks_garbled(t):
    if not t.strip():
        return True, "empty"
    if "\ufffd" in t:
        return True, "replacement-char"
    m = GARBAGE.search(t)
    if m and any(ch.islower() for ch in m.group(0)) and any(ch.isupper() for ch in m.group(0)):
        return True, "base64-like"
    if re.search(r"(.)\1{6,}", t):
        return True, "char-repeat"
    return False, ""


rows, tok = [], []
for name, prompt, n, kw in SETS:
    for rep in range(1, 4):
        o = gen(prompt, n)[0]
        g, why = looks_garbled(o["text"])
        ok = (not g) and (kw is None or kw.lower() in o["text"].lower())
        rows.append({"case": "%s-r%d" % (name, rep), "ok": ok, "garbled": why,
                     "chars": len(o["text"]), "tok_s": round(o["tok_s"], 2),
                     "head": o["text"][:80].replace("\n", " ")})
        tok.append(o["tok_s"])
for name, prompt, n, kw in EXTRA:
    system = "You are a helpful assistant." if name == "sys" else None
    o = gen(prompt, n, system=system)[0]
    g, why = looks_garbled(o["text"])
    ok = (not g) and (kw is None or kw.lower() in o["text"].lower())
    rows.append({"case": name, "ok": ok, "garbled": why, "chars": len(o["text"]),
                 "tok_s": round(o["tok_s"], 2), "head": o["text"][:80].replace("\n", " ")})
    tok.append(o["tok_s"])

ok_n = sum(1 for r in rows if r["ok"])
print(json.dumps({"model": MODEL, "ok": ok_n, "total": len(rows),
                  "bad_markers": [r["case"] for r in rows if r["garbled"]],
                  "tok_s_median": round(statistics.median(tok), 2),
                  "tok_s_min": round(min(tok), 2), "tok_s_max": round(max(tok), 2)}, ensure_ascii=False))
for r in rows:
    print("%-12s ok=%-5s %-14s %6.2f t/s %4d chars | %s" %
          (r["case"], r["ok"], r["garbled"] or "-", r["tok_s"], r["chars"], r["head"]))
