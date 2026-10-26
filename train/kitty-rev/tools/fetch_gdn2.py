#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_gdn2.py —— 用 curl.exe 走 HTTP（urllib 在 hf-mirror 上会挂），精确取 192 个 GDN 张量并组装 safetensors"""
import argparse, json, os, struct, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE = f"https://hf-mirror.com/{REPO}/resolve/main"
TREE = f"https://hf-mirror.com/api/models/{REPO}/tree/main?recursive=1"
CURL = os.environ.get("CURL_BIN", "curl")
UA = "Mozilla/5.0"

SUFFIXES = [
    "linear_attn.in_proj_qkv.weight", "linear_attn.in_proj_z.weight", "linear_attn.out_proj.weight",
    "linear_attn.in_proj_a.weight", "linear_attn.in_proj_b.weight", "linear_attn.A_log",
    "linear_attn.dt_bias", "linear_attn.conv1d.weight", "linear_attn.norm.weight",
]


def curl_bytes(url, rng=None, retries=6, max_time=600):
    for i in range(retries):
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        cmd = [CURL, "-4", "-fsSL", "--retry", "3", "--connect-timeout", "15",
               "--max-time", str(max_time), "-H", f"User-Agent: {UA}", "-o", tmp]
        if rng:
            cmd += ["-r", rng]
        cmd.append(url)
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and os.path.getsize(tmp) > 0:
            with open(tmp, "rb") as f:
                data = f.read()
            os.unlink(tmp)
            return data
        os.path.exists(tmp) and os.unlink(tmp)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"curl failed: {url} range={rng}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tmp/_gdn/model.safetensors")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--tree", default="")
    a = ap.parse_args()

    tree = json.loads(open(a.tree, encoding="utf-8").read()) if a.tree else json.loads(curl_bytes(TREE, max_time=120).decode())
    sizes = {x["path"]: x["size"] for x in tree if x.get("type") == "file" and x["path"].endswith(".safetensors")}
    shards = sorted(sizes)
    print(f"[1/4] 分片 {len(shards)} 个", flush=True)

    def hdr(f):
        size = sizes[f]
        head = curl_bytes(f"{BASE}/{f}", f"0-{min(4<<20, size-1)}", max_time=300)
        (hlen,) = struct.unpack("<Q", head[:8])
        js = json.loads(head[8:8 + hlen].decode())
        js.pop("__metadata__", None)
        return f, js, 8 + hlen

    with ThreadPoolExecutor(max_workers=6) as ex:
        hdrs = list(ex.map(hdr, shards))
    print("[2/4] header 解析完成", flush=True)

    plan = []
    for f, tensors, data_off in hdrs:
        for name, info in tensors.items():
            if "layers." in name and any(name.endswith(s) for s in SUFFIXES):
                s, e = info["data_offsets"]
                plan.append((name, f, data_off + s, e - s, info["dtype"], info["shape"]))
    total = sum(p[3] for p in plan)
    print(f"[2/4] 目标 {len(plan)} 个 · 合计 {total/2**30:.2f} GiB", flush=True)

    got, lock = {}, __import__("threading").Lock()
    cnt = [0]

    WD = os.path.join(os.path.dirname(a.out) or ".", "work")
    os.makedirs(WD, exist_ok=True)

    def binpath(name):
        return os.path.join(WD, name.replace("/", "_") + ".bin")

    def fetch(it):
        name, f, start, n, dtype, shape = it
        bp = binpath(name)
        if os.path.exists(bp) and os.path.getsize(bp) == n:
            with lock:
                got[name] = (bp, dtype, shape); cnt[0] += 1
            return
        blob = curl_bytes(f"{BASE}/{f}", f"{start}-{start+n-1}", max_time=1200)
        if len(blob) != n:
            raise RuntimeError(f"size mismatch {name} {len(blob)}!={n}")
        with open(bp, "wb") as w:
            w.write(blob)
        with lock:
            got[name] = (bp, dtype, shape)
            cnt[0] += 1
            if cnt[0] % 10 == 0:
                tot = sum(os.path.getsize(v[0]) for v in got.values())
                print(f"    {cnt[0]}/{len(plan)}  {tot/2**30:.2f} GiB", flush=True)

    print(f"[3/4] {a.workers} 路并行", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(fetch, plan))
    print(f"[3/4] 取完 {len(got)}/{len(plan)}", flush=True)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    header, off, order = {}, 0, sorted(got)
    for name in order:
        p_, dtype, shape = got[name]
        n_ = os.path.getsize(p_)
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [off, off + n_]}
        off += n_
    hb = json.dumps(header, separators=(",", ":")).encode()
    hb += b" " * ((8 - len(hb) % 8) % 8)
    with open(a.out, "wb") as f:
        f.write(struct.pack("<Q", len(hb)))
        f.write(hb)
        for name in order:
            with open(got[name][0], "rb") as r:
                while True:
                    c = r.read(64 << 20)
                    if not c: break
                    f.write(c)
    print(f"[4/4] 写出 {a.out} size={os.path.getsize(a.out)} tensors={len(order)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
