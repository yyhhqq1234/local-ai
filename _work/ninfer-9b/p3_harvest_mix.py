# p3_harvest_mix.py — 混合语料采集 MTP 训练数据
# 语料 = 之前 MTP 训练用的 mix-mtp-2k.jsonl（门控创作/常规 + kitty RE 混合）
#      + 当前线上分布 kitty-reverse/train-kitty-v3-clean.jsonl
# 按 token 约 1:1 交叉取块；每块独立起引擎（dump 每进程只落一次），转 npz 后删 bin。
import json
import os
import struct
import subprocess
import sys
import time
import http.client
import numpy as np

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
OUTDIR = os.path.join(WORK, r"mtp-data")
PORT = 18970
MAXTOK = 8
CHAR_LIMIT = 4000

CORPORA = [
    # (路径, 权重)  —— 旧 MTP 语料优先吃满，再用当前分布补齐
    (os.path.join(ROOT, r"train\lines\9b-oxcoder\data\nsfw-gated\mix-mtp-2k.jsonl"), 0.5),
    (os.path.join(ROOT, r"train\lines\9b-oxcoder\data\kitty-reverse\train-kitty-v3-clean.jsonl"), 0.5),
]

PS = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
      "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def kill_own():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split("\t")
        if len(p) >= 2 and p[1].strip().lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", p[0].strip(), "/F"], capture_output=True)


def req(path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def parse_dump(path):
    raw = open(path, "rb").read()
    T, W, R, V, D = struct.unpack_from("<iqiii", raw, 0)
    off = 24
    ids = np.frombuffer(raw, dtype=np.int32, count=T, offset=off).copy(); off += 4 * T
    off += 4 * T
    off += 4 * T * R
    n = W * T
    hidden = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    return T, W, ids, hidden.reshape(T, W)


def iter_chunks(path, limit_chars=CHAR_LIMIT):
    """把 jsonl 里的 user+assistant 拼成 ~limit_chars 的块"""
    buf, size = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msgs = d.get("messages") or []
            user = next((m.get("content") for m in msgs if m.get("role") == "user"), None)
            asst = next((m.get("content") for m in msgs if m.get("role") == "assistant"), None)
            if not asst:
                continue
            buf.append(((user + "\n\n") if user else "") + asst)
            size += len(buf[-1]) + 2
            if size >= limit_chars:
                yield "\n\n".join(buf)[:limit_chars]
                buf, size = [], 0
    if buf:
        yield "\n\n".join(buf)[:limit_chars]


def mixed_chunks(n_total):
    gens = [iter_chunks(p) for p, _ in CORPORA]
    weights = [w for _, w in CORPORA]
    # 先把每个语料的配额算出来（按权重），不足时轮流取
    quota = [max(1, int(round(n_total * w))) for w in weights]
    taken = [0] * len(CORPORA)
    while sum(taken) < n_total:
        progressed = False
        for i, g in enumerate(gens):
            if taken[i] >= quota[i]:
                continue
            try:
                text = next(g)
            except StopIteration:
                quota[i] = taken[i]
                continue
            taken[i] += 1
            progressed = True
            yield f"src{i}", text
            if sum(taken) >= n_total:
                break
        if not progressed:
            break


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    os.makedirs(OUTDIR, exist_ok=True)
    meta_path = os.path.join(OUTDIR, "index.jsonl")
    dump = os.path.join(OUTDIR, "_current.bin")
    t_all = time.perf_counter()
    tok_total = 0
    for i, (src, text) in enumerate(mixed_chunks(start + limit)):
        if i < start:
            continue
        if os.path.exists(dump):
            os.remove(dump)
        kill_own(); time.sleep(0.4)
        env = dict(os.environ)
        env["NINFER_TRACE_MTP_PREFILL"] = dump
        env["NINFER_PREFILL_MAX_TOKENS"] = "64"
        fh = open(os.path.join(WORK, "p3-harvest-mix.log"), "ab")
        argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
                "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
                "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT)]
        p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        pt = None
        try:
            ready = False
            for _ in range(240):
                time.sleep(0.5)
                if p.poll() is not None:
                    break
                try:
                    st, m = req("/v1/models", timeout=2)
                    if st == 200 and m.get("data"):
                        ready = True; break
                except Exception:
                    pass
            if not ready:
                print("chunk %d(%s): engine not ready" % (i, src)); continue
            mid = req("/v1/models")[1]["data"][0]["id"]
            st, d = req("/v1/chat/completions", {"model": mid,
                                                "messages": [{"role": "user", "content": text}],
                                                "max_tokens": MAXTOK, "temperature": 0})
            pt = (d.get("usage") or {}).get("prompt_tokens")
        finally:
            try: p.kill()
            except Exception: pass
            fh.close(); time.sleep(0.3); kill_own()
        if not os.path.exists(dump):
            print("chunk %d(%s): NO DUMP (prompt %s)" % (i, src, pt)); continue
        T, W, ids, hidden = parse_dump(dump)
        out = os.path.join(OUTDIR, "m%05d.npz" % i)
        np.savez_compressed(out, ids=ids, hidden=hidden)
        os.remove(dump)
        tok_total += T
        with open(meta_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"chunk": i, "src": src, "T": T, "W": W,
                                "prompt_tokens": pt, "npz": os.path.basename(out)}) + "\n")
        print("chunk %d(%s): T=%d prompt=%s -> %s" % (i, src, T, pt, os.path.basename(out)))
        sys.stdout.flush()
    wall = time.perf_counter() - t_all
    print("done: %d tokens in %.0fs (%.1f tok/s)" % (tok_total, wall, tok_total / max(1e-9, wall)))


if __name__ == "__main__":
    main()
