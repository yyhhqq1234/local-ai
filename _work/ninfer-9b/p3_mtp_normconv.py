# p3_mtp_normconv.py — is the MTP norm weight stored raw (apply w) or offset (apply 1+w)?
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
off += 4 * T + 4 * T * RCOLS


def take(n):
    global off
    a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    off += 2 * n
    return (a.astype(np.uint32) << 16).view(np.float32)


hidden = torch.from_numpy(take(W * T).reshape(T, W))

from safetensors import safe_open
with safe_open(MTP, framework="pt", device="cpu") as f:
    fc = f.get_tensor("mtp.fc.weight").float()
    hnorm = f.get_tensor("mtp.pre_fc_norm_hidden.weight").float()
    enorm = f.get_tensor("mtp.pre_fc_norm_embedding.weight").float()
    inorm = f.get_tensor("mtp.layers.0.input_layernorm.weight").float()
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
with safe_open(BASE + r"\model.safetensors", framework="pt", device="cpu") as f:
    emb_w = f.get_tensor("model.language_model.embed_tokens.weight").float()
    lm = f.get_tensor("lm_head.weight").float()
    base_fnorm = f.get_tensor("model.language_model.norm.weight").float()
print("base final norm mean = %.4f   mtp.norm mean = %.4f" % (base_fnorm.mean(), fnorm.mean()))

qa = qp.view(HEADS, 2, HD, -1)
q_w = qa[:, 0].reshape(HEADS * HD, -1)
g_w = qa[:, 1].reshape(HEADS * HD, -1)
UNIT = [True]


def rmsnorm(x, w):
    x = x.float()
    return (x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + EPS)) * ((1.0 + w) if UNIT[0] else w)


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


def block(stem_ids, upto):
    e = rmsnorm(emb_w[torch.from_numpy(stem_ids)], enorm)
    h = rmsnorm(hidden, hnorm)
    x = torch.cat([h, e], -1) @ fc.T
    ah = rmsnorm(x, inorm)
    q = (ah @ q_w.T).reshape(T, HEADS, HD)
    k = (ah @ kw.T).reshape(T, KVH, HD)
    v = (ah @ vw.T).reshape(T, KVH, HD)
    g = (ah @ g_w.T).reshape(T, HEADS, HD)
    rp = np.arange(T)
    qn = rope_apply(rmsnorm(q, qnw), rp)
    kn = rope_apply(rmsnorm(k, knw), rp)
    rep = HEADS // KVH
    sc = torch.einsum("hd,thd->ht", qn[upto], kn[: upto + 1].repeat_interleave(rep, 1)) / (HD ** 0.5)
    at = torch.softmax(sc, -1)
    ao = torch.einsum("ht,thd->hd", at, v[: upto + 1].repeat_interleave(rep, 1))
    gated = (ao * torch.sigmoid(g[upto])).reshape(-1)
    xr = gated @ ow.T + x[upto]
    mh = rmsnorm(xr, pan)
    xmlp = (torch.nn.functional.silu(mh @ gw.T) * (mh @ uw.T)) @ dw.T + xr
    return rmsnorm(xmlp, fnorm) @ lm.T


for unit in (True, False):
    UNIT[0] = unit
    hit = tot = 0
    preds = []
    for t in range(T - 2):
        p = int(block(ids, t).argmax())
        preds.append(p)
        hit += int(p == int(ids[t + 1]))
        tot += 1
    print("unit=%-5s  MTP top1==ids[t+1]: %d/%d  distinct=%d  preds=%s"
          % (unit, hit, tot, len(set(preds)), preds))
print("ids[t+1] =", ids[1:T - 1].tolist())
