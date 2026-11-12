# p3_layer_check.py — 用 TRACE_AR 的 x（引擎 proposal 输入）+ 我们头权重，离线算 argmax，
# 与 DUMP_DRAFT 里的引擎 draft / target 对比。判据：argmax==draft 的比例 ≈100% → 头与引擎一致。
import importlib.util
import os
import re
import sys
import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
AR = os.path.join(BASE, "align-m64-ar.bin")
DR = os.path.join(BASE, "align-m64-draft.txt")
HEAD = os.environ.get("MTP_HEAD", os.path.join(BASE, "mtp-out", "mtp-tuned-dump.safetensors"))
W = 4096

spec = importlib.util.spec_from_file_location("tr", os.path.join(BASE, "p3_mtp_train.py"))
tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)

raw = open(AR, "rb").read()
T = len(raw) // (W * 2)
x_np = np.frombuffer(raw, dtype=np.uint16, count=T * W).reshape(T, W)
x = torch.from_numpy(x_np).view(torch.bfloat16).float().unsqueeze(0)
print("ar records:", T)

tgt, drf, anchors = [], [], []
for line in open(DR, encoding="utf-8"):
    m = re.search(r"anchor=(-?\d+) target=(\d+) \| draft=(\S*)", line)
    if not m:
        continue
    anchors.append(int(m.group(1)))
    tgt.append(int(m.group(2)))
    d = m.group(3).strip()
    drf.append(int(d) if d else -1)

n = min(T, len(tgt))
print("draft lines:", len(tgt), "use:", n)

sd = load_file(HEAD)
for k in list(sd):
    if k.endswith(".weight") and "norm" in k:
        sd[k] = sd[k].float() + 1.0
layer = tr.M.MTPLayer(tr.CFG, sd).float().eval().to("cuda")

emb, lm = tr.load_embed_head("cuda")
xs = x[:, :n].to("cuda")
with torch.no_grad():
    # 两种假设：A) x 已是 fc 之后（只跑层内）；B) x 仍是主干 hidden（跑完整 stem，但缺 emb → 跳过）
    cos, sin = tr.M.rope_tables(layer.attn.head_dim, xs.shape[1], layer.theta, xs.device, xs.dtype)
    h = xs + layer.attn(layer.input_norm(xs), cos, sin)[0]
    h = h + layer.mlp(layer.post_attention_norm(h))
    o = layer.final_norm(h)
    pred = F.linear(o[0].to(lm.dtype), lm).argmax(-1).tolist()
    a_ids = torch.tensor(anchors[:n], dtype=torch.long)
    of = layer(xs, emb[a_ids].to("cuda").unsqueeze(0), base_lm_head=None)
    predf = F.linear(of[0].to(lm.dtype), lm).argmax(-1).tolist()

same_draft = sum(1 for i in range(n) if drf[i] == pred[i])
same_tgt = sum(1 for i in range(n) if tgt[i] == pred[i])
eng_ok = sum(1 for i in range(n) if drf[i] == tgt[i])
print("offline argmax == engine draft : %d/%d = %.3f" % (same_draft, n, same_draft / n))
print("offline argmax == target       : %d/%d = %.3f" % (same_tgt, n, same_tgt / n))
print("engine draft  == target        : %d/%d = %.3f" % (eng_ok, n, eng_ok / n))
print("FULL-head argmax == engine draft: %d/%d" % (sum(1 for i in range(n) if drf[i]==predf[i]), n))
print("FULL-head argmax == target      : %d/%d" % (sum(1 for i in range(n) if tgt[i]==predf[i]), n))
print("sample: pred", pred[:8], "draft", drf[:8], "target", tgt[:8])
