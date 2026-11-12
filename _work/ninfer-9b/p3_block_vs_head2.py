# p3_block_vs_head2.py — 用同一份引擎 dump，扫"norm 偏移约定 × rope 维度"四个组合，找与引擎 cosine 最高的那个
import importlib.util
import os
import struct
import sys
import numpy as np
import torch
from safetensors.torch import load_file

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
DUMP = os.path.join(BASE, "p3-block-new.bin")
HEAD = os.path.join(BASE, "mtp-out", "mtp-tuned-dump.safetensors")

spec = importlib.util.spec_from_file_location("tr", os.path.join(BASE, "p3_mtp_train.py"))
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)


def parse(path):
    raw = open(path, "rb").read()
    T, W, RCOLS = struct.unpack_from("<iq i", raw, 0)
    off = 16 + 4 * T + 4 * T * RCOLS

    def take(n):
        nonlocal off
        a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
        off += 2 * n
        return (a.astype(np.uint32) << 16).view(np.float32)

    ah = take(W * T).reshape(T, W)
    take(256 * 16 * T); take(256 * 4 * T); take(256 * 4 * T); take(256 * 16 * T)
    out = take(W * T).reshape(T, W)
    return T, W, ah, out


T, W, ah, out_eng = parse(DUMP)
b = out_eng.reshape(-1).astype(np.float64)
print("dump T=%d" % T)

base_sd = load_file(HEAD)
QK = ("mtp.layers.0.self_attn.q_norm.weight", "mtp.layers.0.self_attn.k_norm.weight")
OTHER = [k for k in base_sd if k.endswith(".weight") and "norm" in k and k not in QK]


def build(qk_off: bool, other_off: bool, rope: str):
    sd = {}
    for k, v in base_sd.items():
        t = v.float()
        if k in QK and qk_off:
            t = t + 1.0
        elif k in OTHER and other_off:
            t = t + 1.0
        sd[k] = t
    layer = tr.M.MTPLayer(tr.CFG, sd).float().eval()
    if rope == "full":
        # 恢复 mtp_posttrain 原生全维 rope
        def full(x, cos, sin):
            v1, v2 = x.chunk(2, dim=-1)
            rot = torch.cat([-v2, v1], dim=-1)
            c = cos[: x.shape[-2]].unsqueeze(0).unsqueeze(0)
            s = sin[: x.shape[-2]].unsqueeze(0).unsqueeze(0)
            return x * c + rot * s
        tr.M.apply_rope = full
    else:
        tr.M.apply_rope = tr._partial_rope
    x = torch.from_numpy(ah).unsqueeze(0)
    with torch.no_grad():
        cos, sin = tr.M.rope_tables(layer.attn.head_dim, x.shape[1], layer.theta, x.device, x.dtype)
        h = x + layer.attn(layer.input_norm(x), cos, sin)[0]
        h = h + layer.mlp(layer.post_attention_norm(h))
        o = layer.final_norm(h)[0].numpy().reshape(-1).astype(np.float64)
    return float((o @ b) / (np.linalg.norm(o) * np.linalg.norm(b) + 1e-12))


for qk in (False, True):
    for other in (False, True):
        for rope in ("partial", "full"):
            c = build(qk, other, rope)
            print("qk_off=%-5s other_off=%-5s rope=%-7s cosine=%.6f" % (qk, other, rope, c))
