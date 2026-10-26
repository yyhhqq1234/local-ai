#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""extract_gdn.py —— 从本地已下好的 HF 分片里按 header 偏移抠出 192 个 GDN 张量，写成 mini safetensors

为什么：merge.py 用 transformers 加载混合架构 → linear_attn(GDN) 未被加载 → merged 里 192 个张量为零。
        LoRA 的 target_modules 不含 linear_attn ⇒ v4 的 GDN == 基座 GDN，直接原样搬即可。
用法：python tools/extract_gdn.py --src tmp/_base --out tmp/_gdn/model.safetensors
"""
import argparse, json, os, struct, sys

SUFFIXES = [
    "linear_attn.in_proj_qkv.weight", "linear_attn.in_proj_z.weight", "linear_attn.out_proj.weight",
    "linear_attn.in_proj_a.weight", "linear_attn.in_proj_b.weight", "linear_attn.A_log",
    "linear_attn.dt_bias", "linear_attn.conv1d.weight", "linear_attn.norm.weight",
]


def read_header(path):
    with open(path, "rb") as f:
        (hlen,) = struct.unpack("<Q", f.read(8))
        js = json.loads(f.read(hlen).decode())
    js.pop("__metadata__", None)
    return hlen, js, 8 + hlen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="tmp/_base")
    ap.add_argument("--out", default="tmp/_gdn/model.safetensors")
    a = ap.parse_args()

    shards = sorted(f for f in os.listdir(a.src) if f.endswith(".safetensors"))
    print(f"[1/3] 本地分片 {len(shards)} 个")
    picked = []
    for s in shards:
        p = os.path.join(a.src, s)
        hlen, tensors, data_off = read_header(p)
        for name, info in tensors.items():
            if "layers." in name and any(name.endswith(x) for x in SUFFIXES):
                picked.append((name, p, data_off, info["data_offsets"], info["dtype"], info["shape"]))
    total = sum(e - b for _, _, _, (b, e), _, _ in picked)
    print(f"[1/3] 命中 {len(picked)} 个张量 · {total/2**30:.2f} GiB")
    if len(picked) < 180:
        print(f"[FAIL] 少于 180 个，源可能不全")
        sys.exit(2)

    print("[2/3] 抠字节")
    header, off, order = {}, 0, []
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    tmp = a.out + ".data"
    with open(tmp, "wb") as w:
        for name, p, data_off, (b, e), dtype, shape in sorted(picked):
            n = e - b
            with open(p, "rb") as f:
                f.seek(data_off + b)
                blob = f.read(n)
            if len(blob) != n:
                print(f"[FAIL] 短读 {name}: {len(blob)}/{n}")
                sys.exit(3)
            header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [off, off + n]}
            ascii_name = name.encode("ascii", "replace")
            if len(ascii_name) != len(name):
                print(f"[WARN] 非 ASCII 名: {name}")
            w.write(blob)
            off += n
            order.append(name)

    print(f"[3/3] 写 safetensors 头（{len(order)} 张量）")
    hb = json.dumps(header, separators=(",", ":")).encode()
    hb += b" " * ((8 - len(hb) % 8) % 8)
    with open(a.out, "wb") as f:
        f.write(struct.pack("<Q", len(hb)))
        f.write(hb)
        with open(tmp, "rb") as r:
            while True:
                chunk = r.read(64 << 20)
                if not chunk:
                    break
                f.write(chunk)
    os.unlink(tmp)
    print(f"[done] {a.out} size={os.path.getsize(a.out)} tensors={len(order)}")

    # 自检：用 safetensors 打开，抽 3 个看是否非零
    from safetensors import safe_open
    with safe_open(a.out, framework="numpy") as f:
        ks = list(f.keys())
        print(f"[self] keys={len(ks)}")
        import numpy as np
        for k in ks[:3]:
            arr = f.get_tensor(k)
            print(f"   {k} shape={arr.shape} dtype={arr.dtype}")


if __name__ == "__main__":
    sys.exit(main())
