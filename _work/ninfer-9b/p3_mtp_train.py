# p3_mtp_train.py — 在「当前量化主干 dump 的 hidden」上重训 1 层 MTP 头
# 数据：_work/ninfer-9b/mtp-data/*.npz（ids + hidden bf16 位），来自混合语料（旧 MTP mix-2k + 当前 kitty 语料）
# 语义（A-18 已证）：hidden[t] 是主干末层输出；ids[t] = x_{t+1}；头用 stem(hidden[t], emb(ids[t])) 预测 ids[t+1]
# 结构：复用 mtp_posttrain.MTPLayer（gated attn + QK-norm + MLP），rope 改为 partial（64/256, half-split）
#       RMSNorm 走 unit-offset (1+w)：初始化时 p = 1+w，导出时 w = p-1
import importlib.util
import json
import math
import os
import sys
import time
import random

import numpy as np
import torch
import torch.nn.functional as F
from safetensors import safe_open
from safetensors.torch import save_file

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
Q = os.path.join(ROOT, r"train\lines\27b-kittyrev\quant\mtp_posttrain.py")
HEAD = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\mtp\merged-2b-nsfw-mtp-tuned-v3-mix600.safetensors.step300.safetensors")
MERGED = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\model.safetensors")
DATA = os.environ.get("MTP_DATA", os.path.join(ROOT, r"_work\ninfer-9b\mtp-data"))
OUT = os.path.join(ROOT, r"_work\ninfer-9b\mtp-out")

spec = importlib.util.spec_from_file_location("mtpmod", Q)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

CFG = {"hidden_size": 4096, "intermediate_size": 12288, "num_attention_heads": 16,
       "num_key_value_heads": 4, "head_dim": 256, "rope_theta": 10_000_000.0}
ROPE_DIM = 64          # partial_rotary_factor 0.25 × 256
CTX = int(os.environ.get("MTP_CTX", "512"))
BATCH = 4


# ── 消融开关（环境变量）：MTP_ROPE=partial|full，MTP_TARGET_SHIFT=1|2，MTP_OUT=<path> ──
ROPE_MODE = os.environ.get("MTP_ROPE", "partial")
TARGET_SHIFT = int(os.environ.get("MTP_TARGET_SHIFT", "2"))
OUT_PATH = os.environ.get("MTP_OUT", "")
SEED = int(os.environ.get("MTP_SEED", "0"))


# ── partial rope（只转前 64 维，half-split）覆盖模块里的全维版本 ──
def _partial_rope(x, cos, sin):
    d = ROPE_DIM
    xr, xp = x[..., :d], x[..., d:]
    v1, v2 = xr.chunk(2, dim=-1)
    rot = torch.cat([-v2, v1], dim=-1)
    c = cos[: x.shape[-2], :d // 2]
    c = torch.cat([c, c], dim=-1).unsqueeze(0).unsqueeze(0)
    s = sin[: x.shape[-2], :d // 2]
    s = torch.cat([s, s], dim=-1).unsqueeze(0).unsqueeze(0)
    return torch.cat([xr * c + rot * s, xp], dim=-1)


if ROPE_MODE == "partial":
    M.apply_rope = _partial_rope


def load_norm_and_head():
    sd = {}
    with safe_open(HEAD, framework="pt", device="cpu") as f:
        for k in f.keys():
            sd[k] = f.get_tensor(k)
    # unit-offset：所有 RMSNorm 参数 p = 1 + w
    for k in list(sd):
        if k.endswith(".weight") and ("norm" in k):
            sd[k] = sd[k].float() + 1.0
    return sd


def load_embed_head(device):
    want = {"model.language_model.embed_tokens.weight": "embed", "lm_head.weight": "lm_head"}
    out = {}
    with safe_open(MERGED, framework="pt", device="cpu") as f:
        for k, alias in want.items():
            out[alias] = f.get_tensor(k)
    emb = out["embed"]              # 留 CPU：只按批索引，省 2 GB 显存
    lm = out["lm_head"].to(device)
    return emb, lm


def list_npz():
    files = sorted(f for f in os.listdir(DATA) if f.endswith(".npz"))
    return files


def load_chunk(path):
    d = np.load(path)
    ids = torch.from_numpy(d["ids"].astype(np.int64))
    hi = torch.from_numpy(d["hidden"])
    hidden = hi.view(torch.bfloat16).to(torch.float32)   # uint16 bits -> bf16 -> fp32
    return ids, hidden


def main():
    os.makedirs(OUT, exist_ok=True)
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    lr = float(sys.argv[2]) if len(sys.argv) > 2 else 5e-4
    device = "cuda"
    files = list_npz()
    if len(files) < 3:
        print("not enough npz:", len(files)); return
    random.seed(SEED); torch.manual_seed(SEED)

    # 留最后 8% 做验证
    n_val = max(1, len(files) // 12)
    train_files, val_files = files[:-n_val], files[-n_val:]

    sd = load_norm_and_head()
    model = M.MTPLayer(CFG, sd).to(device).float()
    for p in model.parameters():
        p.requires_grad_(True)
    emb, lm_head = load_embed_head(device)
    print("vocab=%d hidden=%d files(train/val)=%d/%d" % (emb.shape[0], emb.shape[1], len(train_files), len(val_files)))

    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.0)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, steps), eta_min=lr * 0.1)

    # LRU cache：无上限会把 370 个 npz（~4.8 GB）全留在内存里，长跑收尾时容易被系统 OOM 杀掉
    from collections import OrderedDict
    cache = OrderedDict()
    CACHE_CAP = 24

    def _load_cached(path):
        if path in cache:
            cache.move_to_end(path)
            return cache[path]
        v = load_chunk(path)
        cache[path] = v
        if len(cache) > CACHE_CAP:
            cache.popitem(last=False)
        return v

    def get_batch(fs):
        hs, es, ts = [], [], []
        for _ in range(BATCH):
            path = os.path.join(DATA, random.choice(fs))
            ids, hidden = _load_cached(path)
            T = ids.numel()
            if T < CTX + 2:
                continue
            start = random.randint(0, T - CTX - 2)
            h = hidden[start:start + CTX]                    # [CTX, 4096]
            # 两种配对假设：
            #   shift=2（默认，A-18）：stem 用 emb(ids[t])，预测 ids[t+1]
            #   shift=1：stem 用 emb(ids[t-1])，预测 ids[t]（即 hidden 与"当前 token"配对）
            if TARGET_SHIFT == 1:
                if start == 0:
                    start = 1
                nxt = ids[start - 1:start - 1 + CTX]
                tgt = ids[start:start + CTX]
            else:
                nxt = ids[start:start + CTX]
                tgt = ids[start + 1:start + 1 + CTX]
            hs.append(h); es.append(nxt); ts.append(tgt)
        if not hs:
            return None
        h = torch.stack(hs).to(device)
        nxt = torch.stack(es)                     # CPU 索引，省显存
        tgt = torch.stack(ts).to(device)
        return h, emb[nxt].to(device), tgt

    t0 = time.time()
    for step in range(1, steps + 1):
        b = get_batch(train_files)
        if b is None:
            continue
        h, emb_next, tgt = b
        out = model(h, emb_next, base_lm_head=None)            # [B,T,h] fp32
        # 分时间片算 logits：整段 [B,512,248320] 会吃 2 GB，切片后峰值 <300 MB
        loss_sum = 0.0
        corr = tot = 0
        for s0 in range(0, out.shape[1], 64):
            o = out[:, s0:s0 + 64]
            # lm_head 保持 bf16（转 fp32 会多占 2 GB）；logits 再转 fp32 做 CE
            lg = F.linear(o.to(lm_head.dtype), lm_head).float()
            tgt_c = tgt[:, s0:s0 + 64]
            loss_sum = loss_sum + F.cross_entropy(lg.reshape(-1, lg.shape[-1]).float(),
                                                 tgt_c.reshape(-1), reduction="sum")
            corr += (lg.argmax(-1) == tgt_c).sum().item()
            tot += tgt_c.numel()
        loss = loss_sum / max(1, tot)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step()
        if step % 25 == 0 or step == 1:
            print("step %4d loss=%.4f top1=%.4f lr=%.2e %.0fs"
                  % (step, loss.item(), corr / max(1, tot), sched.get_last_lr()[0], time.time() - t0))
            sys.stdout.flush()
        if step % 100 == 0:
            save_head(model, os.path.join(OUT, "mtp-tuned-dump.step%d.safetensors" % step))
    if not OUT_PATH:
        save_head(model, os.path.join(OUT, "mtp-tuned-dump.safetensors"))
        print("saved:", os.path.join(OUT, "mtp-tuned-dump.safetensors"))
    if OUT_PATH:
        save_head(model, OUT_PATH)
        print("saved variant:", OUT_PATH)
    try:
        import psutil
        print("MB avail: %.0f" % (psutil.virtual_memory().available/1e6))
    except Exception:
        pass
    # 验证集 top1
    if val_files:
        with torch.no_grad():
            tot = corr = 0
            for f in val_files:
                ids, hidden = load_chunk(os.path.join(DATA, f))
                T = ids.numel()
                if T < 64:
                    continue
                h = hidden[: T - 2].unsqueeze(0).to(device)
                nxt = ids[: T - 2].unsqueeze(0).to(device)
                tgt = ids[1: T - 1].to(device)
                out = model(h, emb[nxt.cpu()].to(device), base_lm_head=None)
                pred = F.linear(out.to(lm_head.dtype), lm_head).argmax(-1)[0]
                corr += (pred == tgt).sum().item(); tot += tgt.numel()
            print("VAL top1 = %.4f (%d tokens)" % (corr / max(1, tot), tot))


def save_head(model, path):
    sd = {}
    for k, v in model.state_dict().items():
        name = k
        name = name.replace("fc.", "mtp.fc.")
        name = name.replace("hidden_norm.", "mtp.pre_fc_norm_hidden.")
        name = name.replace("embedding_norm.", "mtp.pre_fc_norm_embedding.")
        name = name.replace("input_norm.", "mtp.layers.0.input_layernorm.")
        name = name.replace("post_attention_norm.", "mtp.layers.0.post_attention_layernorm.")
        name = name.replace("final_norm.", "mtp.norm.")
        name = name.replace("attn.", "mtp.layers.0.self_attn.")
        name = name.replace("mlp.gate.", "mtp.layers.0.mlp.gate_proj.")
        name = name.replace("mlp.up.", "mtp.layers.0.mlp.up_proj.")
        name = name.replace("mlp.down.", "mtp.layers.0.mlp.down_proj.")
        t = v.detach().float().cpu()
        # 导出回 unit-offset 原始参数：w = p - 1
        if "norm" in name and name.endswith(".weight") and t.dim() == 1:
            t = t - 1.0
        sd[name] = t.to(torch.bfloat16)
    save_file(sd, path)


if __name__ == "__main__":
    main()
