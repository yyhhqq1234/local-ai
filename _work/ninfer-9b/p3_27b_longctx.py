"""27B 长上下文验证：起始用 kv=8192 / ctx=262144 / host-kv=8192（设备 KV 池 + 主机流式）。
测不同 prompt 长度下的 prefill、TTFT，并在结束后读显存余量。
"""
import json
import subprocess
import sys
import time
import http.client

PORT = 8080
MODEL = "j27b"
SMI = r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_540239129807163b\nvidia-smi.exe"
UNIT = "本地推理把模型放在用户机器上运行，数据不出域，延迟低，成本可控。"


def free_mb():
    out = subprocess.run([SMI, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return int(out.splitlines()[0]) if out else -1


def chat(prompt, n=16):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": n, "temperature": 0, "stream": False}
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=3600)
    c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
              headers={"Content-Type": "application/json"})
    r = c.getresponse(); d = json.loads(r.read()); c.close()
    return d


def make_prompt(approx_tokens):
    n = max(1, approx_tokens // 20)
    return "以下是工程笔记，请用一句话总结：\n" + UNIT * n


for target in (int(x) for x in sys.argv[1:] or ["8000", "32000", "100000"]):
    p = make_prompt(target)
    t0 = time.time()
    d = chat(p)
    dt = time.time() - t0
    t = d.get("timings") or {}
    usage = d.get("usage") or {}
    print(json.dumps({
        "target_tokens": target,
        "prompt_tokens": usage.get("prompt_tokens"),
        "prefill_tok_s": round(t.get("prompt_per_second") or 0, 1),
        "ttft_s": round((t.get("prompt_ms") or 0) / 1000, 2),
        "wall_s": round(dt, 1),
        "free_vram_mb_after": free_mb(),
        "ok": bool(((d.get("choices") or [{}])[0].get("message") or {}).get("content") is not None),
    }, ensure_ascii=False), flush=True)
