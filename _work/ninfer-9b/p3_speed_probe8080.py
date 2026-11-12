import json
import re
import statistics
import http.client

PORT = 8080
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."


def chat(prompt, n):
    body = {"model": "x", "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=900)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    t = d.get("timings") or {}
    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return txt, (t.get("predicted_per_second") or 0)


chat("warmup", 8)
speeds = []
bad = 0
for _ in range(4):
    txt, sp = chat(FIXED, 256)
    speeds.append(sp)
    if "\ufffd" in txt or re.search(r"(.)\1{6,}", txt):
        bad += 1
print(json.dumps({"speed_all": [round(x, 1) for x in speeds],
                  "median": round(statistics.median(speeds), 2),
                  "min": round(min(speeds), 2), "garbled": bad}, ensure_ascii=False))
