# p3_norm_sweep.py — 不再信离线 cosine（已证不可靠），直接按"导出约定"打 artifact 测引擎 accepted
# 约定 S = 引擎会做 (1+w) 的 norm 组；对不在 S 的组，写盘时要 +1（抵消训练时的 p=1+w）
import json
import os
import struct
import subprocess
import sys
import time
import http.client
from safetensors.torch import load_file, save_file

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
BASE = os.path.join(ROOT, r"_work\ninfer-9b")
PY = os.path.join(ROOT, r"train\.venv\Scripts\python.exe")
CONV_CWD = os.path.join(ROOT, r"train\lines\_shared\tools\ninfer-master")
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
DST = os.path.join(BASE, r"merged-mtp-new")
OUTDIR = os.path.join(ROOT, r"train\lines\9b-oxcoder\out")
HEAD = os.path.join(BASE, r"mtp-out", "mtp-tuned-dump.safetensors")
PORT = 18996

G = {
    "pre": ("mtp.pre_fc_norm_hidden.weight", "mtp.pre_fc_norm_embedding.weight"),
    "in": ("mtp.layers.0.input_layernorm.weight",),
    "post": ("mtp.layers.0.post_attention_layernorm.weight",),
    "final": ("mtp.norm.weight",),
    "qk": ("mtp.layers.0.self_attn.q_norm.weight", "mtp.layers.0.self_attn.k_norm.weight"),
}
COMBO = [
    ("S-in-post-final", {"in", "post", "final"}),
    ("S-pre-in-post-final", {"pre", "in", "post", "final"}),
    ("S-all", set(G)),
    ("S-none", set()),
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
        r = c.getresponse(); raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    finally:
        c.close()


def write_head(S, out_path):
    sd = load_file(HEAD)
    out = {}
    for k, v in sd.items():
        t = v.float()
        if k.endswith(".weight"):
            for g, keys in G.items():
                if k in keys and g not in S:
                    t = t + 1.0      # 该组引擎不做 offset → 存回 p
        out[k] = t.to(v.dtype)
    save_file(out, out_path)
    return out_path


def patch_head(path):
    def rd(p):
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            return n, json.loads(f.read(n).decode("utf-8"))
    n_dst, h_dst = rd(os.path.join(DST, "model.safetensors"))
    n_h, h_h = rd(path)
    keys = [k for k in h_h if k.startswith("mtp") and k != "__metadata__"]
    n_ok = 0
    with open(path, "rb") as fh, open(os.path.join(DST, "model.safetensors"), "r+b") as fd:
        for k in keys:
            if k not in h_dst or h_dst[k]["shape"] != h_h[k]["shape"]:
                continue
            s, e = h_h[k]["data_offsets"]
            fh.seek(8 + n_h + s); data = fh.read(e - s)
            ds, de = h_dst[k]["data_offsets"]
            if len(data) != de - ds:
                continue
            fd.seek(8 + n_dst + ds); fd.write(data); n_ok += 1
    return n_ok


def measure(art):
    kill_own(); time.sleep(0.5)
    env = dict(os.environ); env["NINFER_PREFILL_MAX_TOKENS"] = "64"
    fh = open(os.path.join(BASE, "norm-sweep-engine.log"), "ab")
    argv = [EXE, art, "--max-context", "4096", "--kv-capacity", "4096", "--greedy",
            "--host-context-mib", "2048", "--prefill-chunk", "128", "--no-thinking",
            "--no-cuda-graph", "--spec", "mtp", "--draft-tokens", "1", "--port", str(PORT)]
    p = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, env=env,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(240):
            time.sleep(0.5)
            if p.poll() is not None:
                return {"ok": False, "error": "engine died"}
            try:
                st, m = req("/v1/models", timeout=2)
                if st == 200 and m.get("data"):
                    break
            except Exception:
                pass
        else:
            return {"ok": False, "error": "not ready"}
        mid = req("/v1/models")[1]["data"][0]["id"]
        st, d = req("/v1/chat/completions", {"model": mid, "max_tokens": 256, "temperature": 0,
                                            "messages": [{"role": "user", "content":
                                                          "Explain why local inference is useful. Give a detailed answer with examples."}]})
        tm = d.get("timings") or {}
        dn, da = tm.get("draft_n") or 0, tm.get("draft_n_accepted") or 0
        return {"ok": st == 200, "decode_tok_s": round(tm.get("predicted_per_second") or 0, 2),
                "draft_n": dn, "accepted": da, "rate": round(da / dn, 4) if dn else None}
    finally:
        try: p.kill()
        except Exception: pass
        fh.close(); time.sleep(0.4); kill_own()


def main():
    res = []
    for name, S in COMBO:
        h = write_head(S, os.path.join(BASE, "mtp-out", "var-%s.safetensors" % name))
        n = patch_head(h)
        art = os.path.join(OUTDIR, "kittyrev-oxcoder9b-%s.ninfer" % name)
        cv = subprocess.run([PY, "-m", "tools.convert", "--model", DST, "--recipe", "recipe_g1_shipped.py",
                             "--components", "text,vision,mtp",
                             "--resource", "video_preprocessor_config.json=video_preprocessor_config.json",
                             "--resource", "tokenizer_config.json=" + os.path.join(BASE, "tokenizer_config_fixed.json"),
                             "--name", "kittyrev-oxcoder9b-" + name, "--out", art],
                            cwd=CONV_CWD, capture_output=True, text=True, timeout=1800)
        if not os.path.exists(art):
            rec = {"variant": name, "error": "convert", "log": (cv.stderr or "")[-200:]}
        else:
            rec = {"variant": name, "patched": n, "measure": measure(art)}
        res.append(rec)
        print(json.dumps(rec, ensure_ascii=False)); sys.stdout.flush()
    print("== summary ==")
    for r in res:
        m = r.get("measure") or {}
        print("%-22s decode=%-6s acc=%-5s rate=%-7s %s" % (r["variant"], m.get("decode_tok_s"),
                                                           m.get("accepted"), m.get("rate"), r.get("error", "")))


if __name__ == "__main__":
    main()
