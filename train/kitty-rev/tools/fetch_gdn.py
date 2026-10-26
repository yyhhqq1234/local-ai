#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_gdn.py —— 按 safetensors header 精确取 HF 基座里的 192 个 GDN 张量，本地组装成一个 mini safetensors

为什么：merge.py 用 transformers 加载混合架构，linear_attn(GDN) 那一族没被加载 → merged-v4 里 192 个张量为零。
        LoRA 的 target_modules 不含 linear_attn，所以 v4 的 GDN == 基座的 GDN（严格相等），可直接搬。
做法：① 拉每个分片的前 4 MiB 解析 header（safetensors: u64 len + JSON + data）
      ② 算出 192 个目标张量的绝对字节区间 → 8 路并行 Range 取
      ③ 在本地拼成一个标准 safetensors（dtype 原样，BF16/F32），文件名 key = HF 原名
用法：python tools/fetch_gdn.py --out tmp/_gdn/model.safetensors --workers 8
"""
import argparse
import json
import os
import struct
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE = f"https://hf-mirror.com/{REPO}/resolve/main"
API = f"https://hf-mirror.com/api/models/{REPO}/tree/main?recursive=1"
UA = {"User-Agent": "Mozilla/5.0"}

# 要取的 GDN 张量后缀（HF 侧名字）
SUFFIXES = [
    "linear_attn.in_proj_qkv.weight",
    "linear_attn.in_proj_z.weight",
    "linear_attn.out_proj.weight",
    "linear_attn.in_proj_a.weight",
    "linear_attn.in_proj_b.weight",
    "linear_attn.A_log",
    "linear_attn.dt_bias",
    "linear_attn.conv1d.weight",
    "linear_attn.norm.weight",
]


def http_range(url, start, end, retries=6, timeout=180):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            want = end - start + 1
            if len(data) == want:
                return data
            # 服务器忽略 Range 时会返回 200 全文件，取尾部对齐
            if len(data) > want:
                return data[-(want):] if r.status == 200 else data[:want]
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def get_shard_list():
    req = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    files = [x["path"] for x in d if x.get("type") == "file" and x["path"].endswith(".safetensors")]
    return sorted(files)


def parse_header(url, size):
    head = http_range(url, 0, min(4 << 20, size - 1))
    (hlen,) = struct.unpack("<Q", head[:8])
    js = json.loads(head[8:8 + hlen].decode("utf-8"))
    meta = js.pop("__metadata__", None)
    return hlen, js, (8 + hlen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tmp/_gdn/model.safetensors")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    shards = get_shard_list()
    print(f"[1/4] 分片 {len(shards)} 个", flush=True)

    # 取各分片 header（并发）
    def hdr(f):
        url = f"{BASE}/{f}"
        # 先要总长
        req = urllib.request.Request(url, headers=UA, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            size = int(r.headers["Content-Length"])
        hlen, tensors, data_off = parse_header(url, size)
        return f, size, hlen, tensors, data_off

    with ThreadPoolExecutor(max_workers=6) as ex:
        hdrs = list(ex.map(hdr, shards))
    print("[2/4] header 解析完成", flush=True)

    plan = []  # (name, shard, abs_start, nbytes, dtype, shape)
    for f, size, hlen, tensors, data_off in hdrs:
        for name, info in tensors.items():
            if not any(name.endswith(s) for s in SUFFIXES):
                continue
            if "layers." not in name:
                continue
            s, e = info["data_offsets"]
            plan.append((name, f, data_off + s, e - s, info["dtype"], info["shape"]))
    print(f"[2/4] 目标张量 {len(plan)} 个 · 合计 {sum(p[3] for p in plan)/2**30:.2f} GiB", flush=True)
    if len(plan) < 180:
        print(f"[WARN] 期望 ~192 个，实得 {len(plan)}", flush=True)

    # 并发取字节
    got = {}
    lock = threading.Lock()
    done = [0]

    def fetch(item):
        name, f, start, n, dtype, shape = item
        url = f"{BASE}/{f}"
        blob = http_range(url, start, start + n - 1)
        with lock:
            got[name] = (blob, dtype, shape)
            done[0] += 1
            if done[0] % 20 == 0:
                print(f"    {done[0]}/{len(plan)}  {sum(len(v[0]) for v in got.values())/2**30:.2f} GiB", flush=True)
        return None

    print(f"[3/4] {a.workers} 路并行取字节", flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(fetch, plan))
    print(f"[3/4] 取完 {len(got)} 个", flush=True)

    # 写标准 safetensors
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    header = {}
    off = 0
    order = sorted(got)
    for name in order:
        blob, dtype, shape = got[name]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [off, off + len(blob)]}
        off += len(blob)
    hb = json.dumps(header, separators=(",", ":")).encode()
    pad = (8 - len(hb) % 8) % 8
    hb += b" " * pad
    with open(a.out, "wb") as f:
        f.write(struct.pack("<Q", len(hb)))
        f.write(hb)
        for name in order:
            f.write(got[name][0])
    print(f"[4/4] 写出 {a.out}  size={os.path.getsize(a.out)}  tensors={len(order)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
