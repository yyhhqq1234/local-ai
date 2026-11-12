# p3_mtp_harvest.py — 采集「当前引擎（量化主干）的 hidden + ids」，用于重训 MTP 头
# 格式（与 p3_mtp_prefill_check.py 一致）：<iq iii> T,W,RCOLS,VOCAB,DRAFT
#   ids[T] int32 · pos[T] int32 · rope[T*RCOLS] int32 · hidden[T*W] bf16 · ah[T*W] bf16 · out[W] bf16
# 关键：MAXTOK 必须 >=8 —— trace 在"生成结束"时 flush，max_tokens=1 时 final=0 不落盘（实测）
import json
import os
import struct
import subprocess
import sys
import time
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
CORPUS = os.path.join(ROOT, r"train\lines\9b-oxcoder\data\kitty-reverse\train-kitty-v3-clean.jsonl")
OUTDIR = os.path.join(WORK, r"mtp-harvest")
PORT = 18960
MAXTOK = 8
CHAR_LIMIT = 4000   # ≈1000-1200 token，避开 128 块边界的 bad allocation

PS_LIST = ("Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
           "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }")


def procs():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    return [(int(x.split("\t")[0]), x.split("\t", 1)[1].strip())
            for x in r.stdout.splitlines() if "\t" in x and x.split("\t", 1)[0].strip().isdigit()]


def kill_own():
    for pid, p in procs():
        if p.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def req(path, payload=None, timeout=600):
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


def start_engine(dump_path):
    env = dict(os.environ)
    env["NINFER_TRACE_MTP_PREFILL"] = dump_path
    # 关键：A-15 把 max_unit_tokens 默认提到 128 后，MTP prefill 在 128-token 单元上 bad_alloc；
    # 覆盖成 64 后 spec prefill 正常（实测 382/3000 token 均可）
    env["NINFER_PREFILL_MAX_TOKENS"] = "64"
    logp = os.path.join(WORK, "p3-harvest.engine.log")
    fh = open(logp, "ab")
    argv = [EXE, MODEL, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1",
            "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(240):
        time.sleep(0.5)
        if p.poll() is not None:
            fh.close()
            raise RuntimeError("engine died: see p3-harvest.engine.log")
        try:
            m = req("/v1/models", timeout=2)
            if isinstance(m, dict) and "data" in m:
                return p, fh, m["data"][0]["id"]
        except Exception:
            pass
    fh.close()
    p.kill()
    raise RuntimeError("engine not ready in 120s")


def load_corpus(n):
    texts, buf, size = [], [], 0
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            msgs = d.get("messages") or []
            asst = next((m.get("content") for m in msgs if m.get("role") == "assistant"), None)
            user = next((m.get("content") for m in msgs if m.get("role") == "user"), None)
            if not asst:
                continue
            buf.append(((user + "\n\n") if user else "") + asst)
            size += len(buf[-1]) + 2
            if size >= CHAR_LIMIT:
                texts.append("\n\n".join(buf)[:CHAR_LIMIT])
                buf, size = [], 0
                if len(texts) >= n:
                    break
    if buf and len(texts) < n:
        texts.append("\n\n".join(buf)[:CHAR_LIMIT])
    return texts[:n]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    os.makedirs(OUTDIR, exist_ok=True)
    texts = load_corpus(n)
    meta = []
    t_all = time.perf_counter()
    for i, text in enumerate(texts):
        dump = os.path.join(OUTDIR, "chunk-%04d.bin" % i)
        if os.path.exists(dump):
            os.remove(dump)
        kill_own()
        time.sleep(0.5)
        proc, fh, mid = start_engine(dump)
        pt = None
        dt = 0.0
        try:
            t0 = time.perf_counter()
            d = req("/v1/chat/completions", {"model": mid,
                                            "messages": [{"role": "user", "content": text}],
                                            "max_tokens": MAXTOK, "temperature": 0, "stream": False})
            dt = time.perf_counter() - t0
            pt = (d.get("usage") or {}).get("prompt_tokens")
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            fh.close()
            time.sleep(0.4)
            kill_own()
        if not os.path.exists(dump):
            print("chunk %d: NO DUMP (prompt %s tokens, %.2fs)" % (i, pt, dt))
            continue
        raw = open(dump, "rb").read(24)
        T, W, R, V, D = struct.unpack_from("<iqiii", raw, 0)
        meta.append({"chunk": i, "file": os.path.basename(dump), "T": T, "W": W,
                     "prompt_tokens": pt, "wall_s": round(dt, 2),
                     "bytes": os.path.getsize(dump), "text_chars": len(text)})
        print("chunk %d: T=%d W=%d prompt=%s wall=%.2fs size=%.1fMB"
              % (i, T, W, pt, dt, os.path.getsize(dump) / 1e6))
    wall = time.perf_counter() - t_all
    with open(os.path.join(OUTDIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"chars_per_chunk": CHAR_LIMIT, "max_tokens": MAXTOK,
                   "chunks": meta, "total_wall_s": round(wall, 1)}, f, ensure_ascii=False, indent=2)
    tok = sum(m["T"] for m in meta)
    print("done: %d chunks, %d tokens, wall %.1fs (%.1f tok/s 采集)"
          % (len(meta), tok, wall, tok / max(1e-9, wall)))


if __name__ == "__main__":
    main()
