# p3_ar_analyse.py — is the proposal input frozen, or swamped by a constant component?
import numpy as np
import torch

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
AR = ROOT + r"\_work\ninfer-9b\p3-ar-dump.bin"
BASE = ROOT + r"\train\lines\9b-oxcoder\models\merged-2b-nsfw"
W = 4096

raw = np.fromfile(AR, dtype=np.uint16)
n = raw.size // W
x = ((raw.astype(np.uint32) << 16).view(np.float32)).reshape(n, W)
print("rows =", n)

rms = np.sqrt((x.astype(np.float64) ** 2).mean(1))
print("rms  first 6 =", np.round(rms[:6], 4).tolist())
print("rms  last  3 =", np.round(rms[-3:], 4).tolist())

cos = (x @ x.T) / (np.linalg.norm(x, axis=1)[:, None] * np.linalg.norm(x, axis=1)[None, :])
print("cos(r0,r1)=%.5f  cos(r0,r30)=%.5f  cos(r30,r31)=%.5f"
      % (cos[0, 1], cos[0, min(30, n - 1)], cos[max(n - 2, 0), n - 1]))

m = x.mean(0)
d = x - m
print("\n|mean| = %.4f   mean|dev| = %.4f   ratio = %.4f"
      % (np.linalg.norm(m), np.linalg.norm(d, axis=1).mean(),
         np.linalg.norm(m) / np.linalg.norm(d, axis=1).mean()))

from safetensors import safe_open
with safe_open(BASE + r"\model.safetensors", framework="pt", device="cpu") as f:
    lm = f.get_tensor("lm_head.weight").float()

for tag, vec in (("mean", m), ("row0", x[0]), ("row31", x[min(31, n - 1)])):
    top = torch.topk(torch.from_numpy(np.ascontiguousarray(vec)) @ lm.T, 5)
    print("%-6s argmax=%-7d top5=%s %s" % (tag, int(top.indices[0]), top.indices.tolist(),
                                           [round(float(v), 2) for v in top.values]))

arg = [(torch.from_numpy(np.ascontiguousarray(x[i])) @ lm.T).argmax().item() for i in range(n)]
print("\nargmax per row (first 12):", arg[:12])
print("distinct argmax:", sorted(set(arg))[:10], " count:", len(set(arg)))
