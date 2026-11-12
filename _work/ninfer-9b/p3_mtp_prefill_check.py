# p3_mtp_prefill_check.py — validate the MTP stem and the id/position pairing
import json
import struct
import numpy as np
import torch

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
DUMP = ROOT + r"\_work\ninfer-9b\p3-mtp-prefill.bin"
MTP = ROOT + r"\train\lines\9b-oxcoder\models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors"
BASE = ROOT + r"\train\lines\9b-oxcoder\models\merged-2b-nsfw"
EPS = 1e-6

raw = open(DUMP, "rb").read()
T, W, RCOLS, VOCAB, DRAFT = struct.unpack_from("<iq i i i", raw, 0)
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
out = take(W)

print("T=%d W=%d rope_cols=%d vocab=%d draft=%d" % (T, W, RCOLS, VOCAB, DRAFT))
print("ids    =", ids.tolist())
print("pos    =", pos.tolist())
print("rope   =", rope.reshape(T, RCOLS)[:, 0].tolist())
print("hidden rms=%.4f  ah rms=%.4f  out rms=%.4f"
      % tuple(float(np.sqrt((x.astype(np.float64) ** 2).mean())) for x in (hidden, ah, out)))

# --- what text do these ids carry? ---
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(BASE)
print("\nids -> text:", repr(tok.decode(ids.tolist())))
prompt = "List three benefits of unit testing."
msgs = [{"role": "user", "content": prompt}]
try:
    full = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True)
except Exception as exc:
    full = tok(prompt).input_ids
    print("(chat template failed: %s)" % exc)
print("prompt len =", len(full))
print("prompt tail ids =", full[-8:])
print("dump ids tail   =", ids.tolist()[-8:])
match = [i for i in range(len(full)) if i + T <= len(full) and full[i:i + T] == ids.tolist()]
print("ids occur in prompt at offset(s):", match)

# --- stem reproduction ---
from safetensors import safe_open
with safe_open(MTP, framework="pt", device="cpu") as f:
    fc = f.get_tensor("mtp.fc.weight").float()
    hnorm = f.get_tensor("mtp.pre_fc_norm_hidden.weight").float()
    enorm = f.get_tensor("mtp.pre_fc_norm_embedding.weight").float()
    inorm = f.get_tensor("mtp.layers.0.input_layernorm.weight").float()

emb_w = None
with safe_open(BASE + r"\model.safetensors", framework="pt", device="cpu") as f:
    keys = [k for k in f.keys() if "embed_tokens" in k]
    print("\nembedding tensors:", keys)
    emb_w = f.get_tensor(keys[0]).float()
print("emb table:", tuple(emb_w.shape))


def rmsnorm(x, w, unit=True):
    x = x.float()
    y = x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + EPS)
    return y * ((1.0 + w) if unit else w)


def rel(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-9))


emb = emb_w[torch.from_numpy(ids)]
hid = torch.from_numpy(hidden)
for unit in (True, False):
    e = rmsnorm(emb, enorm, unit)
    h = rmsnorm(hid, hnorm, unit)
    for order, stem in (("h_first", torch.cat([h, e], -1)), ("e_first", torch.cat([e, h], -1))):
        x = stem @ fc.T
        ah_ref = rmsnorm(x, inorm, unit)
        print("unit=%-5s order=%-8s rel(ah)=%.5f  x_rms=%.4f ah_rms=%.4f"
              % (unit, order, rel(ah_ref.numpy(), ah), float(x.pow(2).mean().sqrt()),
                 float(ah_ref.pow(2).mean().sqrt())))
