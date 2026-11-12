import json
import statistics
import http.client

PORT = 8080
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."
UNIT = "本地推理把模型放在用户机器上运行，数据不出域，延迟低，成本可控。"


def chat(prompt, n):
    body = {"model": "x", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3600)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


chat("warmup", 8)
sp = []
for _ in range(3):
    d = chat(FIXED, 256)
    sp.append((d.get("timings") or {}).get("predicted_per_second") or 0)
print(json.dumps({"decode_short_median": round(statistics.median(sp), 2),
                  "all": [round(x, 1) for x in sp]}, ensure_ascii=False))

# 长上下文下的 decode：先塞 32k 再生成
big = "以下是工程笔记：\n" + UNIT * 1600
d = chat(big, 8)
t = d.get("timings") or {}
st = chat("基于上面的笔记，再写 32 个字。", 8)
d2 = chat(big, 128)
t2 = d2.get("timings") or {}
print(json.dumps({"ctx32k_decode_tok_s": round(t2.get("predicted_per_second") or 0, 2),
                  "ctx32k_prompt_tokens": (d2.get("usage") or {}).get("prompt_tokens")},
                 ensure_ascii=False))
