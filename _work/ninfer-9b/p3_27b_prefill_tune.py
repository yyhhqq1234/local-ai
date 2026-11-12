import json
import os
import subprocess
import sys
import time
import urllib.request
import http.client

PKG = r"D:\BaiduNetdiskDownload\Local-AI\engines\ninfer-27b\ninfer-27b-kv-stream-3arch-20261019"
sys.path.insert(0, PKG)
os.chdir(PKG)
import launcher  # noqa: E402

PORT = 8080
LONG = ("以下是工程笔记，请阅读后总结要点：\n" + ("本地推理把模型放在用户机器上运行，数据不出域。" * 200))
FIXED = "Explain why local inference is useful. Give a detailed answer with examples."


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


def kill_engine():
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)


def bench():
    def chat(prompt, n):
        body = {"model": "j27b", "messages": [{"role": "user", "content": prompt}],
                "max_tokens": n, "temperature": 0, "stream": False}
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=1800)
        c.request("POST", "/v1/chat/completions", body=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"})
        r = c.getresponse(); d = json.loads(r.read()); c.close()
        return d

    chat("warmup", 8)
    d1 = chat(FIXED, 128)
    t1 = d1.get("timings") or {}
    d2 = chat(LONG, 16)
    t2 = d2.get("timings") or {}
    return {"decode_tok_s": round(t1.get("predicted_per_second") or 0, 2),
            "mtp_draft": t1.get("draft_n"), "mtp_accept": t1.get("draft_n_accepted"),
            "prompt_tokens": (d2.get("usage") or {}).get("prompt_tokens"),
            "prefill_tok_s": round(t2.get("prompt_per_second") or 0, 1),
            "ttft_ms": round(t2.get("prompt_ms") or 0, 1)}


def run_chunk(chunk, kv, ctx):
    kill_engine()
    pre = launcher.preflight("8g-fast")
    profile = pre["profile"]
    arch = pre["arch"]["arch"]
    argv = list(pre["command"]["argv"])
    set_arg(argv, "--prefill-chunk", chunk)
    set_arg(argv, "--kv-capacity", kv)
    set_arg(argv, "--max-context", ctx)
    set_arg(argv, "--host-kv-mib", 1024)
    set_arg(argv, "--max-concurrency", 1)
    pass  # 27B 这版没有 --no-thinking（会打印 usage 后退出）
    log_path = os.path.join(PKG, "logs", "tune-%d.log" % chunk)
    open(log_path, "wb").close()
    with open(log_path, "ab", buffering=0) as fh:
        p = subprocess.Popen(argv, cwd=str(launcher.ENGINES / arch),
                             env=launcher.build_env(spec=launcher.load_profiles(), profile=profile),
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=0x00000010 | 0x00000200)
    ok = False
    for _ in range(30):
        time.sleep(2)
        if p.poll() is not None:
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % PORT, timeout=2).read()
            ok = True
            break
        except Exception:
            pass
    if not ok:
        tail = ""
        with open(log_path, encoding="utf-8", errors="ignore") as fh:
            lines = [l for l in fh.read().splitlines() if "FATAL" in l or "ERROR" in l]
            tail = lines[-1] if lines else "(no error line)"
        return {"chunk": chunk, "kv": kv, "ctx": ctx, "error": tail[:180]}
    res = bench()
    res.update({"chunk": chunk, "kv": kv, "ctx": ctx})
    return res


for chunk, kv, ctx in [(128, 4096, 8192), (256, 4096, 8192), (512, 4096, 8192), (1024, 4096, 8192),
                       (512, 2048, 4096)]:
    print(json.dumps(run_chunk(chunk, kv, ctx), ensure_ascii=False), flush=True)


