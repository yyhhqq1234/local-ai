# p3_block_vs_head4.py — 用 dump 里的真实 positions 构造 rope（此前用 0..T-1 是错的），再扫 norm 组合
import importlib.util
import itertools
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
DUMP = os.path.join(BASE, "p3-mtp-block.bin")
HEAD = os.path.join(BASE, "mtp-out", "mtp-tuned-dump.safetensors")

spec = importlib.util.spec_from_file_location("tr", os.path.join(BASE, "p3_mtp_train.py"))
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)

GROUPS = {
    "pre": ("mtp.pre_fc_norm_hidden.weight", "mtp.pre_fc_norm_embedding.weight"),
    "in": ("mtp.layers.0.input_layernorm.weight",),
    "post": ("mtp.layers.0.post_attention_layernorm.weight",),
    "final": ("mtp.norm.weight",),
    "qk": ("mtp.layers.0.self_attn.q_norm.weight", "mtp.layers.0.self_attn.k_norm.weight"),
}

raw = open(DUMP, "rb").read()
T, W, RCOLS = struct.unpack_from("<iq i", raw, 0)
off = 16
pos = np.frombuffer(raw, dtype=np.int32, count=T, offset=off).copy(); off += 4 * T
off += 4 * T * RCOLS


def take(n):
    global off
    a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    off += 2 * n
    return (a.astype(np.uint32) << 16).view(np.float32)


ah = take(W * T).reshape(T, W)
take(256 * 16 * T); take(256 * 4 * T); take(256 * 4 * T); take(256 * 16 * T)
out_eng = take(W * T).reshape(T, W)
b = out_eng.reshape(-1).astype(np.float64)
print("dump T=%d positions=%s" % (T, pos.tolist()))

base = load_file(HEAD)
HD = 256
theta = 10_000_000.0
inv = 1.0 / (theta ** (torch.arange(0, HD, 2, dtype=torch.float32) / HD))


def rope_at(positions):
    t = torch.tensor(positions, dtype=torch.float32)
    f = torch.outer(t, inv)
    emb = torch.cat([f, f], dim=-1)
    return emb.cos(), emb.sin()


COSP, SINP = rope_at(pos.tolist())


def build(offsets):
    sd = {}
    for k, v in base.items():
        t = v.float()
        for g, keys in GROUPS.items():
            if g in offsets and k in keys:
                t = t + 1.0
        sd[k] = t
    layer = tr.M.MTPLayer(tr.CFG, sd).float().eval()
    tr.M.apply_rope = tr._partial_rope
    x = torch.from_numpy(ah).unsqueeze(0)
    with torch.no_grad():
        h = x + layer.attn(layer.input_norm(x), COSP, SINP)[0]
        h = h + layer.mlp(layer.post_attention_norm(h))
        o = layer.final_norm(h)[0].numpy().reshape(-1).astype(np.float64)
    return float((o @ b) / (np.linalg.norm(o) * np.linalg.norm(b) + 1e-12))


res = []
for r in range(0, 4):
    for combo in itertools.combinations(["pre", "in", "post", "final", "qk"], r):
        res.append((build(set(combo)), combo))
res.sort(reverse=True)
for c, combo in res[:8]:
    print("cosine=%.6f  offsets=%s" % (c, ",".join(combo) or "(none)"))
