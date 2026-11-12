# p3_mtp_stem_check.py — stage-by-stage comparison of engine MTP stem vs torch reference
import numpy as np
import torch
from safetensors import safe_open

WORK = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
DUMP = WORK + r"\p3-mtp-stem.bin"
MTP = (r"D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\models\mtp"
       r"\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors")
EPS = 1e-6

raw = open(DUMP, "rb").read()
T = int(np.frombuffer(raw, dtype=np.int32, count=1, offset=0)[0])
width = int(np.frombuffer(raw, dtype=np.uint64, count=1, offset=4)[0])
off = 12
def take(count, dtype):
    global off
    arr = np.frombuffer(raw, dtype=dtype, count=count, offset=off).copy()
    off += np.dtype(dtype).itemsize * count
    return arr

ids = take(T, np.int32)
hidden = take(width * T, np.uint16)
emb = take(width * T, np.uint16)
eng_e = take(width * T, np.uint16)
eng_h = take(width * T, np.uint16)
eng_fc_in = take(2 * width * T, np.uint16)
eng_x = take(width * T, np.uint16)
eng_ah = take(width * T, np.uint16)

def bf16(bits, rows):
    f = (bits.astype(np.uint32) << 16).view(np.float32)
    return torch.from_numpy(f.reshape(rows, T).copy())

hidden_t, emb_t = bf16(hidden, width), bf16(emb, width)
eng_e_t, eng_h_t = bf16(eng_e, width), bf16(eng_h, width)
eng_fc_t = bf16(eng_fc_in, 2 * width)
eng_x_t, eng_ah_t = bf16(eng_x, width), bf16(eng_ah, width)

with safe_open(MTP, framework="pt", device="cpu") as f:
    hnorm = f.get_tensor("mtp.pre_fc_norm_hidden.weight").float()
    enorm = f.get_tensor("mtp.pre_fc_norm_embedding.weight").float()
    fc = f.get_tensor("mtp.fc.weight").float()
    inorm = f.get_tensor("mtp.layers.0.input_layernorm.weight").float()

def rms(x):
    return float(x.float().pow(2).mean().sqrt())

def rel(a, b):
    a, b = a.float(), b.float()
    return float((a - b).norm() / (b.norm() + 1e-9))

def norm(x, w, mode):
    y = x.float() / torch.sqrt(x.float().pow(2).mean(0, keepdim=True) + EPS)
    if mode == "plain":
        return y * w[:, None]
    if mode == "unit":
        return y * (1.0 + w)[:, None]
    return y

print("T=%d width=%d ids=%s" % (T, width, ids.tolist()))
print("rms: emb=%.4f hidden=%.4f | engine e=%.4f h=%.4f fc_in=%.4f x=%.4f ah=%.4f"
      % (rms(emb_t), rms(hidden_t), rms(eng_e_t), rms(eng_h_t), rms(eng_fc_t),
         rms(eng_x_t), rms(eng_ah_t)))

for mode in ("plain", "unit", "none"):
    e = norm(emb_t, enorm, mode)
    h = norm(hidden_t, hnorm, mode)
    print("norm=%-5s  rel(e)=%.5f rel(h)=%.5f  (ref rms e=%.4f h=%.4f)"
          % (mode, rel(e, eng_e_t), rel(h, eng_h_t), rms(e), rms(h)))

# Which half of fc_in holds the engine's e / h?
print("fc_in low half  vs e: rel=%.5f   vs h: rel=%.5f"
      % (rel(eng_fc_t[:width], eng_e_t), rel(eng_fc_t[:width], eng_h_t)))
print("fc_in high half vs e: rel=%.5f   vs h: rel=%.5f"
      % (rel(eng_fc_t[width:], eng_e_t), rel(eng_fc_t[width:], eng_h_t)))

for mode in ("plain", "unit"):
    e = norm(emb_t, enorm, mode)
    h = norm(hidden_t, hnorm, mode)
    for order, stem in (("h,e", torch.cat([h, e], 0)), ("e,h", torch.cat([e, h], 0))):
        x = fc @ stem
        ah = norm(x, inorm, mode)
        print("norm=%-5s stem=%-3s  rel(x)=%.5f rel(ah)=%.5f x_rms=%.4f"
              % (mode, order, rel(x, eng_x_t), rel(ah, eng_ah_t), rms(x)))

# Is engine ah a normalization of engine x?
for mode in ("plain", "unit"):
    print("engine ah vs norm(engine x, %s): rel=%.5f" % (mode, rel(norm(eng_x_t, inorm, mode), eng_ah_t)))
print("engine x vs fc @ engine_fc_in: rel=%.5f  x_rms=%.4f"
      % (rel(fc @ eng_fc_t, eng_x_t), rms(fc @ eng_fc_t)))
