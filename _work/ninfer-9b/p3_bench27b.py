import json
import http.client
import statistics

PORT = 8080
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."
LONG = ("以下是工程笔记，请阅读后总结要点：\n" + ("本地推理把模型放在用户机器上运行，数据不出域。" * 200))


def chat(prompt, n):
    body = {"model": "j27b", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=1800)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


d = chat("warmup", 8)
print("warmup ok")
sp, ttft = [], None
texts = []
for _ in range(3):
    d = chat(FIXED, 192)
    t = d.get("timings") or {}
    sp.append(t.get("predicted_per_second") or 0)
    texts.append(((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
print(json.dumps({
    "decode_all": [round(x, 2) for x in sp],
    "decode_median": round(statistics.median(sp), 2),
    "usage": d.get("usage"),
    "timings": d.get("timings"),
    "head": texts[-1][:70].replace("\n", " "),
}, ensure_ascii=False))

dl = chat(LONG, 16)
tl = dl.get("timings") or {}
print(json.dumps({"long_prompt_tokens": (dl.get("usage") or {}).get("prompt_tokens"),
                  "prefill_tok_s": round(tl.get("prompt_per_second") or 0, 1),
                  "ttft_ms": round(tl.get("prompt_ms") or 0, 1)}, ensure_ascii=False))
