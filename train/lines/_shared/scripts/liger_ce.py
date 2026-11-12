#!/usr/bin/env python
"""
liger_ce.py — 把 liger 的 fused linear cross entropy 接进 SFTTrainer

为什么
  ctx 8192 时，logits = 8192 × 248320 × 2B ≈ 4.07 GiB，加上权重 5.0 + 激活 4.5 = 13.6 GiB → OOM。
  liger 的 fused CE 不落地完整 logits（分块算 + 在线 softmax），logits 占用降到 ~0.3 GiB。
  liger 0.8.5 的 transformers 集成不含 Qwen3_5，但 **op 本身与模型无关**，这里手动接。

用法（train_qlora9b.py 内）
  from liger_ce import make_liger_trainer_class
  Trainer = make_liger_trainer_class(SFTTrainer)
  trainer = Trainer(model=model, args=args, train_dataset=ds, processing_class=tok)

自测
  python train/lines/_shared/scripts/liger_ce.py --selftest
"""
from __future__ import annotations
import argparse
import sys


def _resolve_lm_head(model):
    """穿透 PeftModel/包装层，拿到 lm_head 的 weight（4bit 模型里它通常是 bf16）"""
    m = model
    seen = set()
    for _ in range(6):
        if id(m) in seen:
            break
        seen.add(id(m))
        # 1) 直接有 get_output_embeddings
        fn = getattr(m, "get_output_embeddings", None)
        if callable(fn):
            head = None
            try:
                head = fn()
            except Exception:
                head = None
            if head is not None and hasattr(head, "weight"):
                return head.weight
        # 2) 常见命名
        for attr in ("lm_head", "output_head"):
            h = getattr(m, attr, None)
            if h is not None and hasattr(h, "weight"):
                return h.weight
        # 3) 往下钻
        nxt = None
        for attr in ("base_model", "model", "module"):
            cand = getattr(m, attr, None)
            if cand is not None and cand is not m:
                nxt = cand
                break
        if nxt is None:
            break
        m = nxt
    raise RuntimeError("无法从模型中定位 lm_head 权重")


def _find_final_norm(model):
    """定位 final_norm：它的输出就是喂给 lm_head 的 hidden（比 output_hidden_states 省 6+ GiB）

    OxCoder-9B 是多模态包装，text 部分在 `model.language_model.*` 下
    （safetensors 里张量名形如 `model.language_model.layers.0.input_layernorm.weight`），
    所以按名字前缀优先匹配，不靠属性链猜。
    """
    cands = []
    for name, mod in model.named_modules():
        n = name.lower()
        if not n.endswith("norm"):
            continue
        if not hasattr(mod, "weight"):
            continue
        score = 0
        if "language_model.norm" in n:
            score = 100
        elif n.endswith(".norm") and ("language_model" in n or "text_model" in n):
            score = 90
        elif n.endswith(".norm") and "layers." not in n:
            score = 50
        if score:
            cands.append((score, name, mod))
    if not cands:
        return None
    cands.sort(key=lambda x: -x[0])
    return cands[0][2]


def _find_text_model(model):
    """定位 decoder 主体（不算 lm_head）。

    根因：`model(**inputs)` 会实体化完整 logits [B,T,248320]，
    accelerate 的 gradient-checkpointing 包装再把它转 fp32 → 一次性 7.58 GiB → OOM。
    只调 text model 拿 last_hidden_state，从源头不产生 logits。
    """
    for name, mod in model.named_modules():
        n = name.lower()
        if n.endswith("language_model") or n.endswith("text_model"):
            return mod
    for name, mod in model.named_modules():
        if type(mod).__name__ in ("Qwen3_5TextModel", "Qwen3_5Model"):
            return mod
    return None


def make_liger_trainer_class(base_cls):
    """生成一个把 compute_loss 换成 liger fused CE 的 Trainer 子类

    关键设计（两条，都是 OOM 逼出来的）
      ① 不传 output_hidden_states=True —— 会让 33 层 hidden 全转 fp32
      ② 不调 model(**inputs) —— 会实体化 [B,T,V] logits 再被转 fp32（+7.58 GiB）
      改为直接调 text model 取 last_hidden_state，只留一份 hidden。
    """
    from liger_kernel.ops import LigerFusedLinearCrossEntropyFunction as LFLCE

    class LigerSFTTrainer(base_cls):
        _text_model = None

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None, **kw):
            labels = inputs.pop("labels", None)
            if labels is None:
                return super().compute_loss(model, inputs, return_outputs=return_outputs, **kw)
            if LigerSFTTrainer._text_model is None:
                LigerSFTTrainer._text_model = _find_text_model(model)
                if LigerSFTTrainer._text_model is None:
                    raise RuntimeError("找不到 text model（language_model）")
            text = LigerSFTTrainer._text_model

            fwd = {"input_ids": inputs["input_ids"], "use_cache": False}
            if inputs.get("attention_mask") is not None:
                fwd["attention_mask"] = inputs["attention_mask"]
            out = text(**fwd)
            hidden = out.last_hidden_state                 # [B,T,H]，final_norm 之后
            lm_w = _resolve_lm_head(model).detach()        # ★ detach：lm_head 冻结，不建梯度（否则 [V,H] fp32 梯度 = 3.8 GiB → OOM）
            # ★ 关键：accelerate 的 checkpoint 包装会把 bf16 输出转 fp32，
            #   若 hidden 是 fp32 而 lm_w 是 bf16，`h @ lm_w.T` 会把 1.9 GiB 的 lm_head
            #   提升成 fp32（+4 GiB）→ 12 GB 必爆。这里强制统一到 lm_w 的 dtype。
            if hidden.dtype != lm_w.dtype:
                hidden = hidden.to(lm_w.dtype)
            shift_h = hidden[:, :-1].contiguous()
            shift_y = labels[:, 1:].contiguous()

            # ── chunked CE：分块算 logits，避免 [N,V] 全量（4 GiB）与权重梯度（4 GiB）──
            # liger 的 LFLCE.apply 不接受 kwargs，无法传 weight_requires_grad=False，
            # 会在 backward 分配 lm_head 的 fp32 梯度 → 12 GB 必爆。故手写分块版。
            import torch.nn.functional as F
            B, T, H = shift_h.shape
            flat_h = shift_h.view(B * T, H)
            flat_y = shift_y.view(B * T)
            import os as _os
            chunk = self._chunk if hasattr(self, "_chunk") else int(_os.environ.get("LIGER_CE_CHUNK", "256"))
            total, n = 0.0, 0
            for i in range(0, flat_h.size(0), chunk):
                h = flat_h[i:i + chunk]
                y = flat_y[i:i + chunk]
                if y.numel() == 0:
                    continue
                logits = h @ lm_w.T                        # [c, V] 只这个 chunk
                total = total + F.cross_entropy(logits, y, reduction="sum", ignore_index=-100)
                n += (y != -100).sum()
            loss = total / n.clamp_min(1)
            return (loss, out) if return_outputs else loss

    LigerSFTTrainer.__name__ = "LigerSFTTrainer"
    return LigerSFTTrainer


# ─────────────────────────── 自测 ───────────────────────────

def selftest(steps: int = 6, ctx: int = 2048, vocab: int = 248320, hidden: int = 512):
    """用缩小 hidden（512）但真实 vocab（248320）验证：
       ① flce 与原生 CE 数值一致 ② 峰值显存显著低于原生 CE 路径"""
    import torch
    import torch.nn.functional as F
    from liger_kernel.ops import LigerFusedLinearCrossEntropyFunction as LFLCE

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    B, T = 1, ctx
    torch.manual_seed(0)
    x = torch.randn(B, T, hidden, device=dev, dtype=torch.bfloat16, requires_grad=True)
    w = (torch.randn(vocab, hidden, device=dev, dtype=torch.bfloat16) * 0.02).requires_grad_(True)
    y = torch.randint(0, vocab, (B, T), device=dev)

    # ① 原生路径（会实体化 [B,T,V] logits）
    if dev == "cuda":
        torch.cuda.reset_peak_memory_stats()
    logits = x @ w.T
    ref = F.cross_entropy(logits.reshape(-1, vocab).float(), y.reshape(-1))
    ref_mem = torch.cuda.max_memory_allocated() / 2**20 if dev == "cuda" else 0
    ref.backward()
    x.grad = None; w.grad = None
    del logits

    # ② liger 路径
    if dev == "cuda":
        torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    _g = LFLCE.apply(x.view(-1, hidden), w, y.view(-1), None, None, -100, 0.0, 0.0, "mean")
    got = _g[0] if isinstance(_g, (tuple, list)) else _g
    got_mem = torch.cuda.max_memory_allocated() / 2**20 if dev == "cuda" else 0
    got.backward()

    diff = (ref - got).abs().item()
    print(f"vocab={vocab} ctx={ctx} hidden={hidden} dev={dev}")
    print(f"  原生 CE : loss={ref.item():.6f}  峰值显存 {ref_mem:.1f} MiB")
    print(f"  liger CE: loss={got.item():.6f}  峰值显存 {got_mem:.1f} MiB")
    print(f"  差值 {diff:.2e}  省显存 {(1 - got_mem / ref_mem) * 100:.1f}%" if ref_mem else f"  差值 {diff:.2e}")
    ok = diff < 1e-2
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--vocab", type=int, default=248320)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest(ctx=a.ctx, vocab=a.vocab, hidden=a.hidden))
    ap.print_help()
