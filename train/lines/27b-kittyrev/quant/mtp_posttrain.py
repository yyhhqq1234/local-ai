#!/usr/bin/env python
"""
mtp_posttrain.py — MTP 头后训练（让投机解码头跟上微调后的主干）

为什么需要
  MTP 的输入是主干的 hidden state。主干一旦 SFT/LoRA 微调，hidden 分布改变，
  官方 MTP 头与新主干"对不齐" → 投机解码接受率下降。
  做法：冻结主干，只用 SFT 数据的前向 hidden 重新训 1 层 MTP。

结构（从 ninfer converter 的 mtp 组件映射反推，tools/convert/qwen3_5.py:944-958）
  mtp/stem_input  = concat( hidden_norm(h_t), embedding_norm(embed(x_{t+1})) )   [B,T,2h]
  mtp/input_projection : mtp.fc.weight        [h, 2h]        → 回到 h
  mtp/layers/0/       : 1 层 full_attention（input_norm → attn(q/k/v/o + q_norm/k_norm)
                        → post_attention_norm → mlp(gate/up/down)）
  mtp/final_norm      : mtp.norm.weight
  → 共享主干的 lm_head（mtp_use_dedicated_embeddings = false）
  → 预测 x_{t+2}

用法
  # 自测（随机权重+随机 token，验证前向与 loss 能降）
  python train/lines/27b-kittyrev/quant/mtp_posttrain.py --selftest --steps 30

  # 真训练（训练完主干、merge 之后跑）
  python train/lines/27b-kittyrev/quant/mtp_posttrain.py \
      --base train/lines/9b-oxcoder/models/merged-v1 \
      --mtp  train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.safetensors \
      --data train/data/re-traj-mix-8k.jsonl \
      --out  train/lines/9b-oxcoder/models/mtp/merged-v1-mtp-tuned.safetensors \
      --steps 2000 --ctx 2048
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F


# ────────────────────────────── 基础块 ──────────────────────────────

class RMSNorm(nn.Module):
    def __init__(self, h: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(h))
        self.eps = eps

    def forward(self, x):
        return self.weight * (x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps))


def rope_tables(head_dim: int, seq: int, theta: float, device, dtype=torch.float32):
    inv = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device, dtype=torch.float32) / head_dim))
    t = torch.arange(seq, device=device, dtype=torch.float32)
    freqs = torch.outer(t, inv)                       # [T, head_dim/2]
    emb = torch.cat([freqs, freqs], dim=-1)           # [T, head_dim]
    return emb.cos().to(dtype), emb.sin().to(dtype)


def apply_rope(x, cos, sin):
    # x: [B, H, T, D]
    def rot(v):
        v1, v2 = v.chunk(2, dim=-1)
        return torch.cat([-v2, v1], dim=-1)
    return x * cos[: x.shape[-2]].unsqueeze(0).unsqueeze(0) + rot(x) * sin[: x.shape[-2]].unsqueeze(0).unsqueeze(0)


class MTPAttention(nn.Module):
    """full attention + QK-norm（与 Qwen3.5 的 full_attention 层一致）"""

    def __init__(self, h, n_heads, n_kv, head_dim, sd, prefix="mtp.layers.0.self_attn."):
        super().__init__()
        self.h, self.n_heads, self.n_kv, self.head_dim = h, n_heads, n_kv, head_dim
        self.q_proj = nn.Linear(h, n_heads * head_dim * 2, bias=False)   # ×2：含 output gate
        self.k_proj = nn.Linear(h, n_kv * head_dim, bias=False)
        self.v_proj = nn.Linear(h, n_kv * head_dim, bias=False)
        self.o_proj = nn.Linear(n_heads * head_dim, h, bias=False)
        self.q_norm = RMSNorm(head_dim)
        self.k_norm = RMSNorm(head_dim)
        self._load(sd, prefix)

    def _load(self, sd, p):
        for name in ("q_proj", "k_proj", "v_proj", "o_proj"):
            w = sd.get(p + name + ".weight")
            if w is not None:
                getattr(self, name).weight.data.copy_(w.to(torch.float32))
        for name in ("q_norm", "k_norm"):
            w = sd.get(p + name + ".weight")
            if w is not None:
                getattr(self, name).weight.data.copy_(w.to(torch.float32))

    def forward(self, x, cos, sin, past=None):
        B, T, _ = x.shape
        gated = self.q_proj(x)
        gate, q = gated.chunk(2, dim=-1)
        q = q.view(B, T, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(B, T, self.n_kv, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(B, T, self.n_kv, self.head_dim).transpose(1, 2)
        q = apply_rope(self.q_norm(q), cos, sin)
        k = apply_rope(self.k_norm(k), cos, sin)
        if past is not None:
            k = torch.cat([past[0], k], dim=2)
            v = torch.cat([past[1], v], dim=2)
        rep = self.n_heads // self.n_kv
        k2, v2 = k.repeat_interleave(rep, dim=1), v.repeat_interleave(rep, dim=1)
        mask = torch.ones(T, k2.shape[2], device=x.device, dtype=torch.bool).tril(
            diagonal=k2.shape[2] - T)
        o = F.scaled_dot_product_attention(q, k2, v2, attn_mask=mask)
        o = o.transpose(1, 2).reshape(B, T, self.n_heads * self.head_dim)
        return self.o_proj(o * gate.sigmoid()), (k, v)


class MTPMLP(nn.Module):
    def __init__(self, h, inter, sd, prefix="mtp.layers.0.mlp."):
        super().__init__()
        self.gate = nn.Linear(h, inter, bias=False)
        self.up = nn.Linear(h, inter, bias=False)
        self.down = nn.Linear(inter, h, bias=False)
        for n in ("gate", "up", "down"):
            w = sd.get(prefix + n + "_proj.weight")
            if w is not None:
                getattr(self, n).weight.data.copy_(w.to(torch.float32))

    def forward(self, x):
        return self.down(F.silu(self.gate(x)) * self.up(x))


class MTPLayer(nn.Module):
    """
    完整 MTP 头：
      stem = concat(hidden_norm(h), embedding_norm(emb))  [B,T,2h]
      x = fc(stem)                                        [B,T,h]
      x = x + attn(input_norm(x))
      x = x + mlp(post_attention_norm(x))
      out = final_norm(x)
    """

    def __init__(self, cfg: dict, sd: dict):
        super().__init__()
        h = cfg["hidden_size"]
        n_heads = cfg["num_attention_heads"]
        n_kv = cfg["num_key_value_heads"]
        head_dim = cfg["head_dim"]
        inter = cfg["intermediate_size"]
        self.h = h
        self.theta = cfg.get("rope_theta", 10_000_000.0)

        self.hidden_norm = RMSNorm(h)
        self.embedding_norm = RMSNorm(h)
        self.fc = nn.Linear(2 * h, h, bias=False)
        self.input_norm = RMSNorm(h)
        self.attn = MTPAttention(h, n_heads, n_kv, head_dim, sd)
        self.post_attention_norm = RMSNorm(h)
        self.mlp = MTPMLP(h, inter, sd)
        self.final_norm = RMSNorm(h)

        # 载入官方权重
        for attr, key in (("hidden_norm", "mtp.pre_fc_norm_hidden.weight"),
                          ("embedding_norm", "mtp.pre_fc_norm_embedding.weight"),
                          ("input_norm", "mtp.layers.0.input_layernorm.weight"),
                          ("post_attention_norm", "mtp.layers.0.post_attention_layernorm.weight"),
                          ("final_norm", "mtp.norm.weight")):
            w = sd.get(key)
            if w is not None:
                getattr(self, attr).weight.data.copy_(w.to(torch.float32))
        w = sd.get("mtp.fc.weight")
        if w is not None:
            self.fc.weight.data.copy_(w.to(torch.float32))

    def forward(self, hidden, emb_next, base_lm_head=None):
        """hidden [B,T,h]（主干 hidden）；emb_next [B,T,h]（下一 token 的 embedding）"""
        stem = torch.cat([self.hidden_norm(hidden), self.embedding_norm(emb_next)], dim=-1)
        x = self.fc(stem)
        cos, sin = rope_tables(self.attn.head_dim, x.shape[1], self.theta, x.device, x.dtype)
        x = x + self.attn(self.input_norm(x), cos, sin)[0]
        x = x + self.mlp(self.post_attention_norm(x))
        out = self.final_norm(x)
        # ★ dtype 对齐：MTP 侧参数是 fp32（融合精度），lm_head 在 4bit/bf16 主干里是 bf16。
        #   不转会报 "expected mat1 and mat2 to have the same dtype, but got: float != BFloat16"
        if base_lm_head is not None:
            w = getattr(base_lm_head, "weight", None)
            if w is not None and out.dtype != w.dtype:
                out = out.to(w.dtype)
            return base_lm_head(out)
        return out


# ────────────────────────────── 训练 / 自测 ──────────────────────────────

def load_mtp(path: Path) -> dict:
    from safetensors.torch import load_file
    return load_file(str(path))


def cfg_from_checkpoint(ckpt: Path) -> dict:
    c = json.loads((ckpt / "config.json").read_text(encoding="utf-8"))
    t = c.get("text_config", c)
    return {
        "hidden_size": t["hidden_size"],
        "intermediate_size": t["intermediate_size"],
        "num_attention_heads": t["num_attention_heads"],
        "num_key_value_heads": t["num_key_value_heads"],
        "head_dim": t.get("head_dim", t["hidden_size"] // t["num_attention_heads"]),
        "rope_theta": (t.get("rope_parameters") or {}).get("rope_theta", 10_000_000.0),
    }


def selftest(steps: int, ctx: int):
    """随机权重 + 随机 token：验证前向通路与 loss 可下降"""
    torch.manual_seed(0)
    h, inter, nh, nkv, hd, vocab = 512, 1536, 8, 2, 64, 4096   # 缩小版，纯验通路
    cfg = {"hidden_size": h, "intermediate_size": inter, "num_attention_heads": nh,
           "num_key_value_heads": nkv, "head_dim": hd, "rope_theta": 1e7}
    sd = {
        "mtp.fc.weight": torch.randn(h, 2 * h) * 0.02,
        "mtp.pre_fc_norm_hidden.weight": torch.ones(h),
        "mtp.pre_fc_norm_embedding.weight": torch.ones(h),
        "mtp.norm.weight": torch.ones(h),
        "mtp.layers.0.input_layernorm.weight": torch.ones(h),
        "mtp.layers.0.post_attention_layernorm.weight": torch.ones(h),
        "mtp.layers.0.self_attn.q_proj.weight": torch.randn(nh * hd * 2, h) * 0.02,
        "mtp.layers.0.self_attn.k_proj.weight": torch.randn(nkv * hd, h) * 0.02,
        "mtp.layers.0.self_attn.v_proj.weight": torch.randn(nkv * hd, h) * 0.02,
        "mtp.layers.0.self_attn.o_proj.weight": torch.randn(nh * hd, h) * 0.02,
        "mtp.layers.0.self_attn.q_norm.weight": torch.ones(hd),
        "mtp.layers.0.self_attn.k_norm.weight": torch.ones(hd),
        "mtp.layers.0.mlp.gate_proj.weight": torch.randn(inter, h) * 0.02,
        "mtp.layers.0.mlp.up_proj.weight": torch.randn(inter, h) * 0.02,
        "mtp.layers.0.mlp.down_proj.weight": torch.randn(h, inter) * 0.02,
    }
    mtp = MTPLayer(cfg, sd)
    head = nn.Linear(h, vocab, bias=False)
    embed = nn.Embedding(vocab, h)
    opt = torch.optim.AdamW(mtp.parameters(), lr=3e-3)
    losses = []
    # 自测要点：输入必须与 label 有因果关系，否则 loss 只能停在 ln(vocab)。
    # 构造 bigram 任务：hidden 用 x1 的 embedding、emb_next 用 x1 的 embedding，
    # label 是紧跟 x1 的真实 next token → MTP 应能学到这个映射。
    for step in range(steps):
        B, T = 2, ctx
        # 确定性可学任务：序列严格递增，next = cur+1 → 模型应能把 loss 压到接近 0
        start = torch.randint(0, vocab - T - 4, (B, 1))
        ids = (start + torch.arange(T + 2).unsqueeze(0)).long()
        hidden = embed(ids[:, :T]).detach()
        emb_next = embed(ids[:, 1:T + 1]).detach()
        logits = mtp(hidden, emb_next, base_lm_head=head)
        loss = F.cross_entropy(logits.reshape(-1, vocab), ids[:, 2:T + 2].reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        losses.append(loss.item())
        if step % max(steps // 5, 1) == 0:
            print(f"  step {step:4d}  loss {loss.item():.4f}")
    first, last = losses[0], losses[-1]
    drop = (first - last) / first * 100
    print(json.dumps({
        "selftest": "PASS" if last < first else "FAIL",
        "loss_first": round(first, 4), "loss_last": round(last, 4),
        "drop_pct": round(drop, 2), "steps": steps, "ctx": ctx,
    }, ensure_ascii=False, indent=2))


def real_train(a):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from safetensors.torch import save_file

    ckpt = Path(a.base)
    cfg = cfg_from_checkpoint(ckpt)
    sd = load_mtp(Path(a.mtp))
    print(f"[info] 主干 {ckpt} | cfg {cfg} | MTP 张量 {len(sd)}", file=sys.stderr)

    tok = AutoTokenizer.from_pretrained(str(ckpt), trust_remote_code=True)
    dtype = torch.bfloat16
    base = AutoModelForCausalLM.from_pretrained(
        str(ckpt), torch_dtype=dtype, device_map="auto", trust_remote_code=True)
    base.eval()
    for p in base.parameters():
        p.requires_grad_(False)

    mtp = MTPLayer(cfg, sd).to(next(base.parameters()).device, dtype=torch.float32)
    mtp.train()
    lm_head = base.get_output_embeddings()
    embed = base.get_input_embeddings()
    for m in (lm_head, embed):
        for p in m.parameters():
            p.requires_grad_(False)

    opt = torch.optim.AdamW(mtp.parameters(), lr=float(a.lr), weight_decay=0.0)
    rows = [json.loads(l) for l in Path(a.data).read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[info] 样本 {len(rows)}", file=sys.stderr)

    # ★ 逐 checkpoint 验证所需：5% 留作验证集 + 权重映射函数 + top-1 评估
    import random
    random.seed(a.seed)
    random.shuffle(rows)
    n_val = max(20, int(len(rows) * a.val_ratio))
    val_rows, rows = rows[:n_val], rows[n_val:]
    print(f"[info] train {len(rows)} / val {len(val_rows)}", file=sys.stderr)

    def _to_sd(m):
        """内存参数名 → safetensors 键名（沿用 converter 的 mtp 组件映射）"""
        return {("mtp.fc.weight" if n == "fc.weight" else
                 "mtp.pre_fc_norm_hidden.weight" if n == "hidden_norm.weight" else
                 "mtp.pre_fc_norm_embedding.weight" if n == "embedding_norm.weight" else
                 "mtp.norm.weight" if n == "final_norm.weight" else
                 "mtp.layers.0.input_layernorm.weight" if n == "input_norm.weight" else
                 "mtp.layers.0.post_attention_layernorm.weight" if n == "post_attention_norm.weight" else
                 "mtp.layers.0.self_attn." + n.split("attn.")[1] if n.startswith("attn.") else
                 # ★ 2026-11-06 修：n.split("mlp.")[1] 得到的是 "gate.weight"（无前导点），
                 #   原写法 .replace(".gate.weight", ...) 带前导点 → 永远匹配不到 →
                 #   产出 mtp.layers.0.mlp.gate.weight（错名），合成时与官方 MTP 键名冲突
                 "mtp.layers.0.mlp." + n.split("mlp.")[1]
                   .replace("gate.weight", "gate_proj.weight")
                   .replace("up.weight", "up_proj.weight")
                   .replace("down.weight", "down_proj.weight")
                 if n.startswith("mlp.") else n)
                : v.detach().to(torch.bfloat16).cpu()
                for n, v in m.named_parameters()}

    def _prep(r):
        txt = "\n".join(m.get("content", "") for m in r.get("messages", []))
        ids = tok(txt, return_tensors="pt", truncation=True, max_length=a.ctx).input_ids
        return ids.to(base.device) if ids.shape[1] >= 8 else None

    @torch.no_grad()
    def eval_top1(tag=""):
        """MTP top-1 与真实下一 token 的一致率 —— 投机解码接受率的近似上界（越高越好）"""
        hit = tot = 0
        for r in val_rows[:60]:
            ids = _prep(r)
            if ids is None:
                continue
            o = base(ids, output_hidden_states=True)
            T = ids.shape[1] - 2
            h = o.hidden_states[-1][:, :T].float()
            e = embed(ids[:, 1:T + 1]).float()
            lg = mtp(h, e, base_lm_head=lm_head)
            pred = lg.argmax(-1)
            hit += (pred == ids[:, 2:T + 2]).sum().item()
            tot += pred.numel()
        acc = hit / max(tot, 1)
        rec = {"step": tag or 0, "mtp_top1": round(acc, 4)}
        print(f"[eval] step={tag} MTP top-1 = {acc:.4f}", file=sys.stderr)
        try:
            with open(str(a.out) + ".history.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return acc

    save_file(_to_sd(mtp), str(a.out) + ".step0.safetensors")
    top1_base = eval_top1("0")
    best = {"step": 0, "top1": top1_base}

    step = 0
    losses = []
    for epoch in range(a.epochs):
        random.shuffle(rows)
        for r in rows:
            txt = "\n".join(m.get("content", "") for m in r.get("messages", []))
            ids = tok(txt, return_tensors="pt", truncation=True, max_length=a.ctx).input_ids
            if ids.shape[1] < 8:
                continue
            ids = ids.to(base.device)
            with torch.no_grad():
                out = base(ids, output_hidden_states=True)
            h_all = out.hidden_states[-1]                     # [B,T,h]
            T = ids.shape[1] - 2
            hidden = h_all[:, :T].float()
            x1 = ids[:, 1:T + 1]
            x2 = ids[:, 2:T + 2]
            with torch.no_grad():
                emb_next = embed(x1).float()
            logits = mtp(hidden, emb_next, base_lm_head=lm_head)
            loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), x2.reshape(-1))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(mtp.parameters(), 1.0)
            # ★ cosine 衰减：原版恒定 lr 5e-4 → 后期在最优点附近震荡不收敛
            if a.lr_min is not None and a.steps:
                prog = min(1.0, step / max(a.steps, 1))
                cur_lr = a.lr_min + 0.5 * (a.lr - a.lr_min) * (1 + math.cos(math.pi * prog))
                for g in opt.param_groups:
                    g["lr"] = cur_lr
            opt.step()
            losses.append(loss.item())
            step += 1
            if step % 20 == 0:
                print(f"  step {step} loss {sum(losses[-20:]) / 20:.4f} "
                      f"lr {opt.param_groups[0]['lr']:.2e}", file=sys.stderr)
            # ★ 逐 checkpoint 保存 + top-1 验证（这是「一个 checkpoint 一个 checkpoint 验」的落点）
            if a.save_every and step % a.save_every == 0:
                p = f"{a.out}.step{step}.safetensors"
                save_file(_to_sd(mtp), p)
                t1 = eval_top1(str(step))
                if t1 > best["top1"]:
                    best.update({"step": step, "top1": t1})
                print(f"[ckpt] step={step} → {p}  top-1={t1:.4f} (best={best['step']}/{best['top1']:.4f})",
                      file=sys.stderr)
            if a.steps and step >= a.steps:
                break
        if a.steps and step >= a.steps:
            break

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out_sd = _to_sd(mtp)
    save_file(out_sd, a.out)
    final_top1 = eval_top1("final")
    if final_top1 > best["top1"]:
        best.update({"step": step, "top1": final_top1})
    print(json.dumps({
        "out": a.out, "tensors": len(out_sd), "steps": step,
        "loss_first": round(losses[0], 4), "loss_last": round(losses[-1], 4),
        "top1_initial": top1_base, "top1_final": final_top1,
        "best": best, "save_every": a.save_every,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--base", default="train/lines/9b-oxcoder/models/merged-v1")
    ap.add_argument("--mtp", default="train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.safetensors")
    ap.add_argument("--data", default="train/data/re-traj-mix-8k.jsonl")
    ap.add_argument("--out", default="train/lines/9b-oxcoder/models/mtp/merged-v1-mtp-tuned.safetensors")
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--lr-min", type=float, default=None,
                    help="给了就启用 cosine 衰减到 lr_min（原版恒定 lr 后期会震荡）")
    ap.add_argument("--save-every", type=int, default=0, dest="save_every",
                    help="每 N 步存一个 {out}.stepN.safetensors 并算 MTP top-1（0=不存）")
    ap.add_argument("--val-ratio", type=float, default=0.05, dest="val_ratio",
                    help="留作验证集的比例，用于算 top-1")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        selftest(a.steps if a.steps != 2000 else 30, a.ctx if a.ctx != 2048 else 64)
    else:
        real_train(a)
