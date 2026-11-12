# -*- coding: utf-8 -*-
"""用字节核算反推真实 ggml type：converter 的 format 判定自洽性验证"""
import json, importlib.util, math, os
fp = r"D:\BaiduNetdiskDownload\Local-AI\_research\csunx\engine\tools\artifact\formats.py"
spec = importlib.util.spec_from_file_location("formats", fp)
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)

p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\local-pack\qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer.conversion.json"
d = json.load(open(p, encoding="utf-8"))
methods = d["methods"]
payload = d["payload_bytes"]
print("PAYLOAD_BYTES", payload)

def numel(shape):
    n = 1
    for s in shape: n *= s
    return n

def size_of(shape, fmt):
    n = numel(shape)
    be, bb = fmt.block_elements, fmt.block_bytes
    if be <= 1:  # 直接格式（bf16=2字节等）
        return n * bb
    return (n + be - 1) // be * bb

total_by_recorded = 0
total_if_iq2s     = 0
total_if_iq2xs    = 0
missing = 0
fmt_count = {}
for m in methods:
    fname = m.get("format")
    shape = m.get("shape") or []
    if not fname or not shape:
        missing += 1; continue
    fmt = F.GGUF_FORMATS.get(fname)
    if fmt is None:
        # 非 gguf 格式（bf16/fp32/q4_g64_fp16 等）
        fmt = F.NUMERIC_FORMATS.get(fname)
        if fmt is None:
            missing += 1; continue
        sz = size_of(shape, fmt)
    else:
        sz = size_of(shape, fmt)
    total_by_recorded += sz
    fmt_count[fname] = fmt_count.get(fname, 0) + 1
    # 反事实：该张量若是 iq2_s / iq2_xs
    if fname in ("gguf_iq2_xs", "gguf_iq2_s"):
        total_if_iq2s  += size_of(shape, F.GGUF_IQ2_S)
        total_if_iq2xs += size_of(shape, F.GGUF_IQ2_XS)

print("methods", len(methods), "missing", missing)
print("按记录的 format 累加 =", total_by_recorded, " diff vs payload =", total_by_recorded - payload)
print("把 iq2 族全按 IQ2_S(82B) 算 =", total_by_recorded - (total_if_iq2s - 0) + 0, "(仅 iq2 张量替换后)", total_by_recorded + (total_if_iq2s - total_if_iq2xs))
print()
print("iq2 族若为 IQ2_XS 时这些张量字节 =", total_if_iq2xs)
print("iq2 族若为 IQ2_S  时这些张量字节 =", total_if_iq2s)
print("差值 (S - XS) =", total_if_iq2s - total_if_iq2xs)
