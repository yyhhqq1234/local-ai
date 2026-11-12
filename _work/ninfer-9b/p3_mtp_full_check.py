# p3_mtp_full_check.py — replay the whole MTP block from (ids, hidden) and compare every segment
import struct
import numpy as np
import torch

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
DUMP = ROOT + r"\_work\ninfer-9b\p3-mtp-prefill-short.bin"
MTP = ROOT + r"\train\lines\9b-oxcoder\models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors"
BASE = ROOT + r"\train\lines\9b-oxcoder\models\merged-2b-nsfw"
EPS = 1e-6
HEADS, KVH, HD = 16, 4, 256
THETA, RDIM = 10000000.0, 64

raw = open(DUMP, "rb").read()
T, W, RCOLS, VOC, DRAFT = struct.unpack_from("<iq i i i", raw, 0)
off = 24
ids = np.frombuffer(raw, dtype=np.int32, count=T, offset=off); off += 4 * T
pos = np.frombuffer(raw, dtype=np.int32, count=T, offset=off); off += 4 * T
rope = np.frombuffer(raw, dtype=np.int32, count=T * RCOLS, offset=off); off += 4 * T * RCOLS


def take(n):
    global off
    a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    off += 2 * n
    return (a.astype(np.uint32) << 16).view(np.float32)


hidden = take(W * T).reshape(T, W)
ah = take(W * T).reshape(T, W)
a_eng = take(HEADS * HD)
xa = take(W)
xr = take(W)
mh = take(W)
out = take(W)
print("T=%d W=%d draft=%d" % (T, W, DRAFT))
print("ids  =", ids.tolist())
print("pos  =", pos.tolist())
print("rope =", rope.reshape(T, RCOLS)[:, 0].tolist())


def rel(a, b):
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    return float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-9))


def rmsnorm(x, w, unit=True):
    x = x.float()
    y = x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + EPS)
    return y * ((1.0 + w) if unit else w)


def rope_apply(x, positions, dim=RDIM):
    Tn, Hn, D = x.shape
    inv = 1.0 / (THETA ** (torch.arange(0, dim, 2, dtype=torch.float32) / dim))
    freqs = torch.outer(torch.tensor(positions, dtype=torch.float32), inv)
    emb = torch.cat([freqs, freqs], dim=-1)
    cos, sin = emb.cos()[:, None, :], emb.sin()[:, None, :]
    head = x[..., :dim]
    x1, x2 = head.chunk(2, dim=-1)
    rot = torch.cat([-x2, x1], dim=-1)
    return torch.cat([head * cos + rot * sin, x[..., dim:]], dim=-1)


from safetensors import safe_open
with safe_open(MTP, framework="pt", device="cpu") as f:
    qp = f.get_tensor("mtp.layers.0.self_attn.q_proj.weight").float()
    kw = f.get_tensor("mtp.layers.0.self_attn.k_proj.weight").float()
    vw = f.get_tensor("mtp.layers.0.self_attn.v_proj.weight").float()
    ow = f.get_tensor("mtp.layers.0.self_attn.o_proj.weight").float()
    qnw = f.get_tensor("mtp.layers.0.self_attn.q_norm.weight").float()
    knw = f.get_tensor("mtp.layers.0.self_attn.k_norm.weight").float()
    pan = f.get_tensor("mtp.layers.0.post_attention_layernorm.weight").float()
    gw = f.get_tensor("mtp.layers.0.mlp.gate_proj.weight").float()
    uw = f.get_tensor("mtp.layers.0.mlp.up_proj.weight").float()
    dw = f.get_tensor("mtp.layers.0.mlp.down_proj.weight").float()
    fnorm = f.get_tensor("mtp.norm.weight").float()

qa = qp.view(HEADS, 2, HD, -1)
q_w = qa[:, 0].reshape(HEADS * HD, -1)
g_w = qa[:, 1].reshape(HEADS * HD, -1)

ah_t = torch.from_numpy(ah)
q_raw = (ah_t @ q_w.T).reshape(T, HEADS, HD)
k_raw = (ah_t @ kw.T).reshape(T, KVH, HD)
v_raw = (ah_t @ vw.T).reshape(T, KVH, HD)
gate_raw = (ah_t @ g_w.T).reshape(T, HEADS, HD)
rp = rope.reshape(T, RCOLS)[:, 0]
qn = rope_apply(rmsnorm(q_raw, qnw), rp)
kn = rope_apply(rmsnorm(k_raw, knw), rp)

# causal attention over the full prompt (no prior cache), last position
last = T - 1
rep = HEADS // KVH
k_rep = kn.repeat_interleave(rep, dim=1)   # [T, HEADS, HD]
v_rep = v_raw.repeat_interleave(rep, dim=1)
scores = torch.einsum("hd,thd->ht", qn[last], k_rep) / (HD ** 0.5)
attn = torch.softmax(scores, dim=-1)       # [HEADS, T]
attn_out = torch.einsum("ht,thd->hd", attn, v_rep)   # [HEADS, HD]
gated = attn_out * torch.sigmoid(gate_raw[last])
print("\na(gated) rel = %.5f   engine rms=%.4f ref rms=%.4f"
      % (rel(gated.numpy(), a_eng), float(np.sqrt((a_eng.astype(np.float64) ** 2).mean())),
         float(gated.pow(2).mean().sqrt())))

o_ref = gated.reshape(-1) @ ow.T
print("o_proj    rel = %.5f" % rel(o_ref.numpy(), xr - xa))
x_res_ref = o_ref + torch.from_numpy(xa)
print("x_res     rel = %.5f" % rel(x_res_ref.numpy(), xr))
mh_ref = rmsnorm(x_res_ref, pan)
print("mh        rel = %.5f" % rel(mh_ref.numpy(), mh))
x_mlp = (torch.nn.functional.silu(mh_ref @ gw.T) * (mh_ref @ uw.T)) @ dw.T + x_res_ref
out_ref = rmsnorm(x_mlp, fnorm)
print("out       rel = %.5f" % rel(out_ref.numpy(), out))

with safe_open(BASE + r"\model.safetensors", framework="pt", device="cpu") as f:
    lm = f.get_tensor("lm_head.weight").float()
top = torch.topk(out_ref @ lm.T, 5)
print("\nreference argmax =", int(top.indices[0]), " engine draft =", DRAFT,
      " match =", int(top.indices[0]) == DRAFT)
print("top5 =", top.indices.tolist(), [round(float(x), 3) for x in top.values])
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(BASE)
print("top5 text =", [repr(tok.decode([int(i)])) for i in top.indices])
print("engine draft text =", repr(tok.decode([DRAFT])))
