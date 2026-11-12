# -*- coding: utf-8 -*-
"""字节核算：converter 记录的 format 是否能精确还原 payload_bytes → 反推真实 ggml type"""
import json

GGUF = {  # name: (ggml_type, block_elements, block_bytes)
 "gguf_q2_k":(10,256,84), "gguf_q3_k":(11,256,110), "gguf_q4_k":(12,256,144),
 "gguf_q5_k":(13,256,176), "gguf_q6_k":(14,256,210), "gguf_iq2_xxs":(16,256,66),
 "gguf_iq2_xs":(17,256,74), "gguf_iq3_xxs":(18,256,98), "gguf_iq1_s":(19,256,50),
 "gguf_iq4_nl":(20,32,18), "gguf_iq3_s":(21,256,110), "gguf_iq2_s":(22,256,82),
 "gguf_iq4_xs":(23,256,136), "gguf_iq1_m":(29,256,56), "gguf_q8_0":(8,32,34),
}
DIRECT = {"bf16":16, "fp32":32, "int32":32}      # bits per element
QBITS  = {"q4_g64_fp16":4, "q5_g64_fp16":5, "q6_g64_fp16":6, "q8_g32_fp16":8, "t2_g128_fp16":2}

def numel(shape):
    n = 1
    for s in shape: n *= s
    return n

def size_of(shape, fname, force=None):
    n = numel(shape)
    key = force or fname
    if key in GGUF:
        _, be, bb = GGUF[key]
        return (n + be - 1) // be * bb
    if key in DIRECT:
        return n * DIRECT[key] // 8
    if key in QBITS:
        return n * QBITS[key] // 8
    return None

p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\local-pack\qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer.conversion.json"
d = json.load(open(p, encoding="utf-8"))
methods, payload = d["methods"], d["payload_bytes"]

as_recorded = 0
as_iq2s = 0          # 把 iq2_xs 张量全换成 iq2_s
iq2xs_bytes = 0
iq2s_bytes = 0
unknown = []
cnt = {}
for m in methods:
    fname, shape = m.get("format"), m.get("shape")
    if not fname or not shape:
        unknown.append((m.get("object"), fname, shape)); continue
    s = size_of(shape, fname)
    if s is None:
        unknown.append((m.get("object"), fname, shape)); continue
    as_recorded += s
    cnt[fname] = cnt.get(fname, 0) + 1
    if fname == "gguf_iq2_xs":
        iq2xs_bytes += size_of(shape, None, "gguf_iq2_xs")
        iq2s_bytes  += size_of(shape, None, "gguf_iq2_s")
    if fname in ("gguf_iq2_xs", "gguf_iq2_s", "gguf_iq3_s", "gguf_q4_k", "gguf_q5_k", "gguf_q8_0"):
        as_iq2s += size_of(shape, None, "gguf_iq2_s") if fname == "gguf_iq2_xs" else s

print("methods         :", len(methods), " unknown/no-shape:", len(unknown))
print("payload_bytes   :", payload)
print("sum(按记录format):", as_recorded, "  差 =", as_recorded - payload)
print("sum(若iq2均S)   :", as_recorded - iq2xs_bytes + iq2s_bytes,
      "  差 =", (as_recorded - iq2xs_bytes + iq2s_bytes) - payload)
print()
print("iq2 张量 iq2_xs 口径 =", iq2xs_bytes)
print("iq2 张量 iq2_s  口径 =", iq2s_bytes, "  两者差 =", iq2s_bytes - iq2xs_bytes)
print()
print("format 计数:", json.dumps(cnt, ensure_ascii=False))
if unknown[:5]: print("unknown sample:", unknown[:5])
