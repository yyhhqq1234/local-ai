#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_gdn3.py —— 稳健版：顺序（不并发）用 curl.exe -4 逐张量取 GDN 权重，断点续取，最后组装 safetensors

为什么顺序：本机并发 curl 会触发 `getaddrinfo() thread failed to start`（DNS 线程耗尽）
为什么 curl -4：IPv6 路径不通，强制 IPv4 才稳定
断点：每个张量落一个 .bin 分块文件，已存在且长度正确的直接跳过；网络断了就退避重试，永不放弃
"""
import argparse, json, os, struct, subprocess, sys, time

REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE = f"https://hf-mirror.com/{REPO}/resolve/main"
CURL = os.environ.get("CURL_BIN", "curl")

SUFFIXES = [
    "linear_attn.in_proj_qkv.weight", "linear_attn.in_proj_z.weight", "linear_attn.out_proj.weight",
    "linear_attn.in_proj_a.weight", "linear_attn.in_proj_b.weight", "linear_attn.A_log",
    "linear_attn.dt_bias", "linear_attn.conv1d.weight", "linear_attn.norm.weight",
]


def curl(url, out, rng=None, timeout=1800):
    cmd = [CURL, "-4", "-fsSL", "--retry", "2", "--speed-limit", "20480", "--speed-time", "90",
           "--connect-timeout", "20", "--max-time", str(timeout), "-o", out]
    if rng:
        cmd += ["-r", rng]
    cmd.append(url)
    return subprocess.run(cmd, capture_output=True).returncode


def get_bytes(url, out, want, rng=None):
    """下载到 out，直到大小 == want；无限重试（退避）"""
    delay = 2
    while True:
        have = os.path.getsize(out) if os.path.exists(out) else 0
        if have == want:
            return True
        if have > want:
            os.unlink(out); have = 0
        r = rng if rng is None or have == 0 else None
        if rng and have:
            # 续取剩余
            s, e = rng.split("-")
            r = f"{int(s)+have}-{e}"
        rc = curl(url, out + ".part", r)
        if rc == 0 and os.path.exists(out + ".part"):
            if have:
                with open(out, "ab") as w, open(out + ".part", "rb") as rd:
                    w.write(rd.read())
            else:
                os.replace(out + ".part", out)
            os.path.exists(out + ".part") and os.unlink(out + ".part")
        else:
            time.sleep(delay)
            delay = min(delay * 1.5, 30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default="tmp/_base/tree.json")
    ap.add_argument("--work", default="tmp/_gdn/work")
    ap.add_argument("--out", default="tmp/_gdn/model.safetensors")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)

    tree = json.load(open(a.tree, encoding="utf-8"))
    sizes = {x["path"]: x["size"] for x in tree if x.get("type") == "file" and x["path"].endswith(".safetensors")}
    shards = sorted(sizes)
    print(f"[1/4] {len(shards)} 分片", flush=True)

    plan = []
    for s in shards:
        hdr_f = os.path.join(a.work, s + ".hdr")
        if not (os.path.exists(hdr_f) and os.path.getsize(hdr_f) > 0):
            get_bytes(f"{BASE}/{s}", hdr_f, None) if False else None
            # header 只取前 2MB
            for _ in range(50):
                rc = curl(f"{BASE}/{s}", hdr_f + ".p", f"0-{min(2<<20, sizes[s]-1)}")
                if rc == 0 and os.path.getsize(hdr_f + ".p") > 8:
                    os.replace(hdr_f + ".p", hdr_f); break
                time.sleep(3)
        with open(hdr_f, "rb") as f:
            (hlen,) = struct.unpack("<Q", f.read(8))
            js = json.loads(f.read(hlen).decode())
        js.pop("__metadata__", None)
        data_off = 8 + hlen
        for name, info in js.items():
            if "layers." in name and any(name.endswith(x) for x in SUFFIXES):
                b, e = info["data_offsets"]
                plan.append((name, s, data_off + b, e - b, info["dtype"], info["shape"]))
        print(f"   {s}: +{sum(1 for p in plan if p[1]==s)} 个", flush=True)

    total = sum(p[3] for p in plan)
    print(f"[2/4] 目标 {len(plan)} 个 · {total/2**30:.2f} GiB", flush=True)

    got = 0; gotb = 0
    for i, (name, s, start, n, dtype, shape) in enumerate(plan):
        out = os.path.join(a.work, name.replace("/", "_") + ".bin")
        ok = get_bytes(f"{BASE}/{s}", out, n, f"{start}-{start+n-1}")
        if ok:
            got += 1; gotb += n
            if got % 10 == 0:
                print(f"   {got}/{len(plan)}  {gotb/2**30:.2f}/{total/2**30:.2f} GiB", flush=True)
        else:
            print(f"   FAIL {name}", flush=True)

    print(f"[3/4] 取到 {got}/{len(plan)}", flush=True)
    header, off = {}, 0
    order = [p[0] for p in plan if os.path.exists(os.path.join(a.work, p[0].replace("/", "_") + ".bin"))]
    for name in order:
        n = os.path.getsize(os.path.join(a.work, name.replace("/", "_") + ".bin"))
        info = next(p for p in plan if p[0] == name)
        header[name] = {"dtype": info[4], "shape": info[5], "data_offsets": [off, off + n]}
        off += n
    hb = json.dumps(header, separators=(",", ":")).encode()
    hb += b" " * ((8 - len(hb) % 8) % 8)
    with open(a.out, "wb") as w:
        w.write(struct.pack("<Q", len(hb))); w.write(hb)
        for name in order:
            with open(os.path.join(a.work, name.replace("/", "_") + ".bin"), "rb") as r:
                while True:
                    c = r.read(64 << 20)
                    if not c: break
                    w.write(c)
    print(f"[4/4] {a.out} size={os.path.getsize(a.out)} tensors={len(order)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
