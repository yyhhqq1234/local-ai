# p3_mtp_block_check.py — compare engine MTP block segments against a torch reference
import json
import struct
import numpy as np
import torch

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
DUMP = ROOT + r"\_work\ninfer-9b\p3-mtp-block.bin"
MTP = ROOT + r"\train\lines\9b-oxcoder\models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors"
EPS = 1e-6
HEADS, KV_HEADS, HD = 16, 4, 256
ROPE_THETA = 10000000.0
ROPE_DIM = 64

raw = open(DUMP, "rb").read()
T, W, RCOLS = struct.unpack_from("<iq i", raw, 0)
off = 16
pos = np.frombuffer(raw, dtype=np.int32, count=T, offset=off); off += 4 * T
rope = np.frombuffer(raw, dtype=np.int32, count=T * RCOLS, offset=off); off += 4 * T * RCOLS


def take(n):
    global off
    a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    off += 2 * n
    return (a.astype(np.uint32) << 16).view(np.float32)


ah = take(W * T).reshape(T, W)
qn = take(HD * HEADS * T).reshape(T, HEADS, HD)
kn = take(HD * KV_HEADS * T).reshape(T, KV_HEADS, HD)
vv = take(HD * KV_HEADS * T).reshape(T, KV_HEADS, HD)
aa = take(HD * HEADS * T).reshape(T, HEADS, HD)
out = take(W * T).reshape(T, W)

print("T=%d W=%d rope_cols=%d" % (T, W, RCOLS))
print("positions =", pos.tolist())
print("rope_positions =", rope.reshape(T, RCOLS)[:, 0].tolist())
print("ah rms=%.4f  qn rms=%.4f  kn rms=%.4f  v rms=%.4f  a rms=%.4f  out rms=%.4f"
      % tuple(float(np.sqrt((x.astype(np.float64) ** 2).mean())) for x in (ah, qn, kn, vv, aa, out)))

from safetensors import safe_open
with safe_open(MTP, framework="pt", device="cpu") as f:
    qp = f.get_tensor("mtp.layers.0.self_attn.q_proj.weight").float()
    kw = f.get_tensor("mtp.layers.0.self_attn.k_proj.weight").float()
    vw = f.get_tensor("mtp.layers.0.self_attn.v_proj.weight").float()
    qnw = f.get_tensor("mtp.layers.0.self_attn.q_norm.weight").float()
    knw = f.get_tensor("mtp.layers.0.self_attn.k_norm.weight").float()

ah_t = torch.from_numpy(ah)


def rel(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-9))


# Layout A: HF / converter per-head interleave [q_h(d), gate_h(d)]
qa = qp.view(HEADS, 2, HD, -1)
q_w_A = qa[:, 0].reshape(HEADS * HD, -1)
g_w_A = qa[:, 1].reshape(HEADS * HD, -1)
# Layout B: flat halves [gate | q]
q_w_B = qp[HEADS * HD:]
g_w_B = qp[:HEADS * HD]

# v is layout independent -> validates ah and the whole stem feeding the block
v_ref = (ah_t @ vw.T).numpy().reshape(T, KV_HEADS, HD)
print("\nv (no norm/rope) rel = %.5f" % rel(v_ref, vv))


def rmsnorm(x, w, unit):
    x = x.float()
    y = x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + EPS)
    return y * ((1.0 + w) if unit else w)


def rope_apply(x, positions, dim):
    # x [T,H,HD]; half-split rotate over first `dim` channels
    Tn, Hn, D = x.shape
    inv = 1.0 / (ROPE_THETA ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    freqs = torch.outer(torch.tensor(positions, dtype=torch.float32), inv)  # [T, dim/2]
    emb = torch.cat([freqs, freqs], dim=-1)                                # [T, dim]
    cos, sin = emb.cos()[:, None, :], emb.sin()[:, None, :]
    head = x[..., :dim]
    x1, x2 = head.chunk(2, dim=-1)
    rot = torch.cat([-x2, x1], dim=-1)
    rotated = head * cos + rot * sin
    return torch.cat([rotated, x[..., dim:]], dim=-1)


for tag, q_w, g_w in (("A per-head [q,g]", q_w_A, g_w_A), ("B halves [gate|q]", q_w_B, g_w_B)):
    q_raw = (ah_t @ q_w.T).reshape(T, HEADS, HD)
    k_raw = (ah_t @ kw.T).reshape(T, KV_HEADS, HD)
    for unit in (True, False):
        qn_ref = rope_apply(rmsnorm(q_raw, qnw, unit), rope.reshape(T, RCOLS)[:, 0], ROPE_DIM)
        kn_ref = rope_apply(rmsnorm(k_raw, knw, unit), rope.reshape(T, RCOLS)[:, 0], ROPE_DIM)
        print("layout=%-20s unit=%-5s rel(qn)=%.5f rel(kn)=%.5f"
              % (tag, unit, rel(qn_ref.numpy(), qn), rel(kn_ref.numpy(), kn)))

# Full-dim rope variant on the best-guess layout
for dim in (ROPE_DIM, HD):
    q_raw = (ah_t @ q_w_A.T).reshape(T, HEADS, HD)
    qn_ref = rope_apply(rmsnorm(q_raw, qnw, True), rope.reshape(T, RCOLS)[:, 0], dim)
    print("rope_dim=%-4d rel(qn)=%.5f" % (dim, rel(qn_ref.numpy(), qn)))
