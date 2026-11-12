# p3_mtp_eval.py — 评估重训后的 MTP 头：分来源 top1（src0=旧 MTP mix-2k，src1=kitty 语料）
import importlib.util
import json
import os
import sys
import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tr", os.path.join(HERE, "p3_mtp_train.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

DATA = tr.DATA
OUT = os.path.join(HERE, r"mtp-out", "mtp-tuned-dump.safetensors")
device = "cuda"


def main():
    files = sorted(f for f in os.listdir(DATA) if f.endswith(".npz"))
    meta = {}
    for line in open(os.path.join(DATA, "index.jsonl"), encoding="utf-8"):
        d = json.loads(line)
        meta[d["npz"]] = d
    val = files[-33:] if len(files) > 40 else files
    sd = load_file(OUT)
    # 导出时做过 w = p-1（引擎侧 unit-offset (1+w)），评估要还原成 p = w+1
    for k in list(sd):
        if k.endswith(".weight") and "norm" in k:
            sd[k] = sd[k].float() + 1.0
    model = tr.M.MTPLayer(tr.CFG, sd).to(device).float().eval()
    emb, lm = tr.load_embed_head(device)
    stats = {}
    with torch.no_grad():
        for f in val:
            ids, hidden = tr.load_chunk(os.path.join(DATA, f))
            T = ids.numel()
            if T < 64:
                continue
            h = hidden[: T - 2].unsqueeze(0).to(device)
            nxt = ids[: T - 2].unsqueeze(0)
            tgt = ids[1: T - 1].to(device)
            out = model(h, emb[nxt].to(device), base_lm_head=None)
            pred = F.linear(out.to(lm.dtype), lm).argmax(-1)[0]
            corr = (pred == tgt).sum().item()
            tot = tgt.numel()
            src = meta.get(f, {}).get("src", "?")
            s = stats.setdefault(src, [0, 0])
            s[0] += corr; s[1] += tot
    allc = sum(v[0] for v in stats.values()); allt = sum(v[1] for v in stats.values())
    for src, (c, t) in sorted(stats.items()):
        print("%s top1 = %.4f (%d tokens)" % (src, c / max(1, t), t))
    print("ALL  top1 = %.4f (%d tokens)" % (allc / max(1, allt), allt))


if __name__ == "__main__":
    main()
