# p3_ablate.py — MTP 接线消融：训练目标位置(H1) × rope 约定(H2) 三组，按"引擎 accepted"定标
# 每组：训 100 步 → 回填 merged-mtp-new → 用原始 recipe 转 artifact → 起引擎测 d1 接受率
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
BASE = os.path.join(ROOT, r"_work\ninfer-9b")
PY = os.path.join(ROOT, r"train\.venv\Scripts\python.exe")
PY2 = r"C:\ProgramData\anaconda3\python.exe"
CONV_CWD = os.path.join(ROOT, r"train\lines\_shared\tools\ninfer-master")
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
DST = os.path.join(BASE, r"merged-mtp-new")
OUTDIR = os.path.join(ROOT, r"train\lines\9b-oxcoder\out")
PORT = 18990
LOG = os.path.join(BASE, "ablation-log.jsonl")

VARIANTS = [
    ("h1-shift1-partial", {"MTP_TARGET_SHIFT": "1", "MTP_ROPE": "partial"}),
    ("h2-shift2-full", {"MTP_TARGET_SHIFT": "2", "MTP_ROPE": "full"}),
    ("h3-shift1-full", {"MTP_TARGET_SHIFT": "1", "MTP_ROPE": "full"}),
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


def req(path, payload=None, timeout=600):
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


def patch_head(head_path):
    def rd(p):
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            return n, json.loads(f.read(n).decode("utf-8"))
    n_dst, h_dst = rd(os.path.join(DST, "model.safetensors"))
    n_h, h_h = rd(head_path)
    keys = [k for k in h_h if k.startswith("mtp") and k != "__metadata__"]
    patched = 0
    with open(head_path, "rb") as fh, open(os.path.join(DST, "model.safetensors"), "r+b") as fd:
        for k in keys:
            if k not in h_dst or h_dst[k]["shape"] != h_h[k]["shape"]:
                continue
            s, e = h_h[k]["data_offsets"]
            fh.seek(8 + n_h + s)
            data = fh.read(e - s)
            ds, de = h_dst[k]["data_offsets"]
            if len(data) != de - ds:
                continue
            fd.seek(8 + n_dst + ds)
            fd.write(data)
            patched += 1
    return patched, len(keys)


def measure(artifact, draft="1"):
    kill_own(); time.sleep(0.5)
    env = dict(os.environ); env["NINFER_PREFILL_MAX_TOKENS"] = "64"
    fh = open(os.path.join(BASE, "ablation-engine.log"), "ab")
    argv = [EXE, artifact, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", draft, "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    out = {"ok": False}
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
            return {"ok": False, "error": "engine not ready"}
        mid = req("/v1/models")[1]["data"][0]["id"]
        st, d = req("/v1/chat/completions", {"model": mid,
                                            "messages": [{"role": "user", "content":
                                                          "Explain why local inference is useful. Give a detailed answer with examples."}],
                                            "max_tokens": 256, "temperature": 0, "stream": False})
        tm = d.get("timings") or {}
        txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        dn = tm.get("draft_n") or 0
        da = tm.get("draft_n_accepted") or 0
        out = {"ok": st == 200, "http": st,
               "decode_tok_s": round(tm.get("predicted_per_second") or 0, 2),
               "draft_n": dn, "accepted": da,
               "accept_rate": round(da / dn, 4) if dn else None,
               "garbled": ("\ufffd" in txt) or bool(__import__("re").search(r"(.)\1{6,}", txt))}
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()
    return out


def main():
    results = []
    for name, envx in VARIANTS:
        head = os.path.join(BASE, "mtp-out", "var-%s.safetensors" % name)
        env = dict(os.environ); env.update(envx); env["MTP_OUT"] = head
        print("== %s train ==" % name); sys.stdout.flush()
        tr = subprocess.run([PY, os.path.join(BASE, "p3_mtp_train.py"), "100", "5e-4"],
                            env=env, capture_output=True, text=True, timeout=1800)
        tail = [l for l in (tr.stdout or "").splitlines() if "step" in l or "VAL" in l][-4:]
        print("   train:", " | ".join(tail))
        if not os.path.exists(head):
            results.append({"variant": name, "error": "no head", "log": (tr.stderr or "")[-300:]}); continue
        patched, total = patch_head(head)
        print("   patched mtp:", patched, "/", total)
        art = os.path.join(OUTDIR, "kittyrev-oxcoder9b-%s.ninfer" % name)
        cv = subprocess.run([PY, "-m", "tools.convert", "--model", DST, "--recipe", "recipe_g1_shipped.py",
                             "--components", "text,vision,mtp",
                             "--resource", "video_preprocessor_config.json=video_preprocessor_config.json",
                             "--resource", "tokenizer_config.json=" + os.path.join(BASE, "tokenizer_config_fixed.json"),
                             "--name", "kittyrev-oxcoder9b-" + name, "--out", art],
                            cwd=CONV_CWD, capture_output=True, text=True, timeout=1800)
        if not os.path.exists(art):
            results.append({"variant": name, "error": "convert failed", "log": (cv.stderr or cv.stdout or "")[-300:]}); continue
        print("   converted:", os.path.basename(art))
        m = measure(art)
        rec = {"variant": name, "env": envx, "train_tail": tail, "measure": m}
        results.append(rec)
        print("   measure:", json.dumps(m, ensure_ascii=False)); sys.stdout.flush()
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("== summary ==")
    for r in results:
        m = r.get("measure") or {}
        print("%-20s decode=%-6s accepted=%-6s rate=%-7s garbled=%s %s"
              % (r["variant"], m.get("decode_tok_s"), m.get("accepted"),
                 m.get("accept_rate"), m.get("garbled"), r.get("error", "")))


if __name__ == "__main__":
    main()
