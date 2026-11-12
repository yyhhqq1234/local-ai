# p3_mtp_tail_check.py — bisect the MTP block tail (o_proj / residual / mlp / final_norm)
import struct
import numpy as np
import torch

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
DUMP = ROOT + r"\_work\ninfer-9b\p3-mtp-prefill.bin"
MTP = ROOT + r"\train\lines\9b-oxcoder\models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors"
EPS = 1e-6

raw = open(DUMP, "rb").read()
T, W, RCOLS, VOCAB, DRAFT = struct.unpack_from("<iq i i i", raw, 0)
off = 24
off += 4 * T          # ids
off += 4 * T          # positions
off += 4 * T * RCOLS  # rope


def take(n):
    global off
    a = np.frombuffer(raw, dtype=np.uint16, count=n, offset=off).copy()
    off += 2 * n
    return (a.astype(np.uint32) << 16).view(np.float32)


hidden = take(W * T).reshape(T, W)
ah = take(W * T).reshape(T, W)
a_out = take(4096)
x_attn = take(W)
x_res = take(W)
mh = take(W)
out = take(W)
print("T=%d W=%d draft=%d" % (T, W, DRAFT))
for name, arr in (("a", a_out), ("x_attn", x_attn), ("x_res", x_res), ("mh", mh), ("out", out)):
    print("  %-7s rms=%.4f" % (name, float(np.sqrt((arr.astype(np.float64) ** 2).mean()))))


def rel(a, b):
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    return float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-9))


def rmsnorm(x, w, unit=True):
    x = x.float()
    y = x / torch.sqrt(x.pow(2).mean(-1, keepdim=True) + EPS)
    return y * ((1.0 + w) if unit else w)


from safetensors import safe_open
with safe_open(MTP, framework="pt", device="cpu") as f:
    ow = f.get_tensor("mtp.layers.0.self_attn.o_proj.weight").float()
    pan = f.get_tensor("mtp.layers.0.post_attention_layernorm.weight").float()
    gw = f.get_tensor("mtp.layers.0.mlp.gate_proj.weight").float()
    uw = f.get_tensor("mtp.layers.0.mlp.up_proj.weight").float()
    dw = f.get_tensor("mtp.layers.0.mlp.down_proj.weight").float()
    fnorm = f.get_tensor("mtp.norm.weight").float()

a_t = torch.from_numpy(a_out)
o_ref = (a_t @ ow.T).numpy()
print("\no_proj(a) rel = %.5f" % rel(o_ref, x_res - x_attn))
x_res_ref = o_ref + x_attn
print("x_res   rel = %.5f" % rel(x_res_ref, x_res))

for unit in (True, False):
    mh_ref = rmsnorm(torch.from_numpy(x_res), pan, unit).numpy()
    print("mh unit=%-5s rel = %.5f" % (unit, rel(mh_ref, mh)))

mlp_ref = (torch.nn.functional.silu(torch.from_numpy(mh) @ gw.T) * (torch.from_numpy(mh) @ uw.T)) @ dw.T
x_mlp_ref = mlp_ref.numpy() + x_res
for unit in (True, False):
    out_ref = rmsnorm(torch.from_numpy(x_mlp_ref), fnorm, unit).numpy()
    print("out unit=%-5s rel = %.5f  (final_norm)" % (unit, rel(out_ref, out)))

# scale-only check: does the engine's out equal the reference up to a positive scalar?
ref = rmsnorm(torch.from_numpy(x_mlp_ref), fnorm, True).numpy()
scale = float(np.dot(out.astype(np.float64), ref.astype(np.float64)) /
              np.dot(ref.astype(np.float64), ref.astype(np.float64)))
print("best scale = %.4f  rel after scale = %.5f" % (scale, rel(ref * scale, out)))
print("cosine(out, ref) = %.5f" % float(
    np.dot(out.astype(np.float64), ref.astype(np.float64)) /
    (np.linalg.norm(out.astype(np.float64)) * np.linalg.norm(ref.astype(np.float64)))))
