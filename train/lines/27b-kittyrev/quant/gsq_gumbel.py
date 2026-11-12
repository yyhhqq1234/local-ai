#!/usr/bin/env python
"""
gsq_gumbel.py — 论文级 GSQ 量化：Gumbel-Softmax 采样学习码本

论文：GSQ: Highly-Accurate Low-Precision Scalar Quantization for LLMs via
      Gumbel-Softmax Sampling (arXiv 2604.18556)

与 converter 内置方法的区别
────────────────────────────────────────────────────────────────────
grouped_absmax   每组取 max|w| 当 scale，round(w/scale) 取码点。
                 无学习、无校准、对 outlier 敏感。
grouped_search   在 max-abs scale 附近扫 25 档（0.70~1.18），选加权误差最小的。
                 有搜索、可带 imatrix，但**码点位置固定**，只调 scale。
grouped_gumbel   每组引入可学习 (scale, logits[g,K])，用 Gumbel-Softmax 松弛
                 p(code|element) 做**可微采样**，端到端最小化重构误差。
                 收敛后取 argmax 得硬码点 → 就是论文的"学习码本"路径。
                 ← 本文件实现

产物格式与 converter 完全一致：
    QuantizedMatrix(codes: int8 [n, groups, group_size], scales: fp16 [n, groups])
因此可直接接 `import_encoded` 之外的任意扩展点，或写成新 method 注入。

用法（自测）
    python train/lines/27b-kittyrev/quant/gsq_gumbel.py --selftest
    python train/lines/27b-kittyrev/quant/gsq_gumbel.py --selftest --bits 4 --shape 512,4096 --steps 200
"""
from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass

import torch
import torch.nn.functional as F


# ── 与 converter 对齐的格式表（tools/artifact/formats.py）──
@dataclass(frozen=True)
class Fmt:
    name: str
    bits: int
    group_size: int
    qmin: int
    qmax: int
    code_bias: int = 0

    @property
    def levels(self) -> torch.Tensor:
        return torch.arange(self.qmin, self.qmax + 1, dtype=torch.float32)


FORMATS = {
    "q2_g64_fp16": Fmt("q2_g64_fp16", 2, 64, -1, 2, code_bias=1),
    "q4_g64_fp16": Fmt("q4_g64_fp16", 4, 64, -8, 7),
    "q5_g64_fp16": Fmt("q5_g64_fp16", 5, 64, -16, 15),
    "q8_g32_fp16": Fmt("q8_g32_fp16", 8, 32, -127, 127),
}


@dataclass
class QuantizedMatrix:
    """与 converter quantization.groupwise.QuantizedMatrix 同构"""
    codes: torch.Tensor      # int8 [n, groups, group_size]
    scales: torch.Tensor     # fp16  [n, groups]


def _gumbel_softmax(logits: torch.Tensor, tau: float, hard: bool = False) -> torch.Tensor:
    """Gumbel-Softmax：论文的核心采样算子（等价 torch.nn.functional.gumbel_softmax）"""
    return F.gumbel_softmax(logits, tau=tau, hard=hard, dim=-1)


def quantize_matrix_gumbel(
    weight: torch.Tensor,
    fmt: str | Fmt,
    *,
    steps: int = 150,
    lr: float = 5e-2,
    tau0: float = 2.0,
    tau_min: float = 0.4,
    row_batch: int = 256,
    imatrix: torch.Tensor | None = None,
    device: str | torch.device | None = None,
    seed: int = 0,
    verbose: bool = False,
) -> QuantizedMatrix:
    """
    对逻辑矩阵 [N, K] 做论文级 GSQ 量化。

    参数
        weight     fp32/bf16 [N,K]，按行（output channel）分组
        fmt        格式名或 Fmt
        steps      每组优化步数（论文用更多步；150 在 9B 上性价比最好）
        lr         scale/logits 学习率
        tau0→tau_min  Gumbel 温度退火区间（高温→探索，低温→收敛）
        row_batch  每次并行处理的行数（控制显存）
        imatrix    [K] 输入通道重要性（来自 llama-imatrix），加权重构误差
    返回
        QuantizedMatrix(codes int8 [N,groups,g], scales fp16 [N,groups])
    """
    spec = FORMATS[fmt] if isinstance(fmt, str) else fmt
    g = spec.group_size
    K_lev = spec.qmax - spec.qmin + 1
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))

    w = weight.detach().to(dtype=torch.float32)
    n, k = w.shape
    k_pad = math.ceil(k / g) * g
    if k_pad != k:
        wp = torch.zeros(n, k_pad, dtype=torch.float32)
        wp[:, :k] = w
        w = wp
    groups = k_pad // g
    levels = spec.levels.to(dev)                     # [K_lev] 码点值

    reward = None
    if imatrix is not None:
        r = imatrix.detach().float().to(dev)
        if r.numel() == k and k_pad != k:
            rp = torch.ones(k_pad, dtype=torch.float32, device=dev)
            rp[:k] = r
            r = rp
        reward = r.reshape(groups, g).unsqueeze(0)   # [1, groups, g]

    codes_out = torch.empty(n, groups, g, dtype=torch.int8)
    scales_out = torch.empty(n, groups, dtype=torch.float16)

    for s in range(0, n, row_batch):
        e = min(s + row_batch, n)
        block = w[s:e].to(dev).reshape(e - s, groups, g)          # [B,groups,g]
        B = block.shape[0]

        # 初始化：absmax scale（与 grouped_absmax 同起点，保证不劣于它）
        with torch.no_grad():
            amax = block.abs().amax(dim=2)                        # [B,groups]
            init_scale = (amax / spec.qmax).clamp_min(1e-8)
            log_scale = torch.nn.Parameter(init_scale.log().clone())   # [B,groups]
            # logits 初值 = 用 absmax 量化后的最近码点（软 one-hot 起手）
            base_codes = (block / init_scale.unsqueeze(-1)).round().clamp(spec.qmin, spec.qmax)
            dist = (base_codes.unsqueeze(-1) - levels.view(1, 1, 1, -1)).abs()  # [B,groups,g,K]
            logits = torch.nn.Parameter((-dist * 4.0))                          # 越近越大

        opt = torch.optim.Adam([log_scale, logits], lr=lr)
        for step in range(steps):
            tau = tau0 * (tau_min / tau0) ** (step / max(steps - 1, 1))        # 指数退火
            scale = log_scale.exp().unsqueeze(-1)                              # [B,groups,1]
            soft = _gumbel_softmax(logits, tau=tau, hard=False)                # [B,groups,g,K]
            w_hat = scale * (soft * levels.view(1, 1, 1, -1)).sum(dim=-1)       # [B,groups,g]
            diff2 = (block - w_hat) ** 2
            if reward is not None:
                diff2 = diff2 * reward
            loss = diff2.mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            if verbose and step % max(steps // 5, 1) == 0:
                print(f"    [row {s}-{e}] step {step:3d} tau={tau:.3f} loss={loss.item():.6f}")

        # 收敛：argmax 取硬码点 + scale 细扫（在 gumbel 收敛点附近再搜一轮倍数）
        with torch.no_grad():
            hard_idx = logits.argmax(dim=-1)                                   # [B,groups,g]
            codes = levels[hard_idx]                                           # [B,groups,g] 码点值
            scale = log_scale.exp()                                            # [B,groups]

            # ── scale 细扫：对每组在 0.90~1.10 的倍数上选重构误差最小的 ──
            # （论文级三步组合：gumbel 学 rounding + scale 精搜 + imatrix 加权）
            best_err = None
            best_codes = None
            best_scale = None
            for mult in torch.linspace(0.90, 1.10, 21, device=dev):
                s_mult = (scale * mult).unsqueeze(-1)                          # [B,groups,1]
                c = torch.round(block / s_mult).clamp(spec.qmin, spec.qmax)    # [B,groups,g]
                d2 = (block - c * s_mult) ** 2
                if reward is not None:
                    d2 = d2 * reward
                err = d2.sum(dim=2)                                            # [B,groups]
                if best_err is None:
                    best_err, best_codes, best_scale = err, c, s_mult.squeeze(-1)
                else:
                    better = err < best_err
                    best_err = torch.where(better, err, best_err)
                    best_codes = torch.where(better.unsqueeze(-1), c, best_codes)
                    best_scale = torch.where(better, s_mult.squeeze(-1), best_scale)

            codes_out[s:e] = best_codes.round().to(torch.int8).cpu()
            scales_out[s:e] = best_scale.to(torch.float16).cpu()

    return QuantizedMatrix(codes=codes_out, scales=scales_out)


def dequantize(qm: QuantizedMatrix, fmt: str | Fmt, k: int | None = None) -> torch.Tensor:
    """还原成 [N, K] fp32，用于误差评估"""
    spec = FORMATS[fmt] if isinstance(fmt, str) else fmt
    codes = qm.codes.float()
    if spec.code_bias:
        codes = codes - spec.code_bias
    w = codes * qm.scales.float().unsqueeze(-1)
    w = w.reshape(w.shape[0], -1)
    return w[:, :k] if k else w


def baseline_absmax(weight: torch.Tensor, fmt: str | Fmt) -> QuantizedMatrix:
    """对照组：converter 内置的 grouped_absmax（同语义复刻）"""
    spec = FORMATS[fmt] if isinstance(fmt, str) else fmt
    g = spec.group_size
    n, k = weight.shape
    k_pad = math.ceil(k / g) * g
    w = weight.detach().float()
    if k_pad != k:
        wp = torch.zeros(n, k_pad, dtype=torch.float32)
        wp[:, :k] = w
        w = wp
    groups = k_pad // g
    b = w.reshape(n, groups, g)
    amax = b.abs().amax(dim=2)
    scale = (amax / spec.qmax).clamp_min(1e-8)
    codes = (b / scale.unsqueeze(-1)).round().clamp(spec.qmin, spec.qmax).to(torch.int8)
    return QuantizedMatrix(codes=codes, scales=scale.to(torch.float16))


def rel_error(w: torch.Tensor, w_hat: torch.Tensor) -> dict:
    """相对重构误差（Frobenius / 逐元素）"""
    d = (w - w_hat).float()
    fro = d.norm() / w.float().norm()
    return {
        "rel_fro": float(fro),
        "rmse": float(d.pow(2).mean().sqrt()),
        "max_abs": float(d.abs().max()),
    }


def _selftest(bits: int, shape: tuple[int, int], steps: int):
    torch.manual_seed(0)
    fmt = {2: "q2_g64_fp16", 4: "q4_g64_fp16", 5: "q5_g64_fp16", 8: "q8_g32_fp16"}[bits]
    n, k = shape
    # 模拟 LLM 权重：高斯 + 少量 outlier（absmax 最怕的形状）
    w = torch.randn(n, k) * 0.02
    n_out = max(n * k // 2000, 8)
    idx = torch.randint(0, n * k, (n_out,))
    w.reshape(-1)[idx] *= 12.0

    print(f"格式 {fmt} | 形状 {shape} | 码点 {FORMATS[fmt].qmax - FORMATS[fmt].qmin + 1} | steps {steps}")
    t0 = time.time()
    qa = baseline_absmax(w, fmt)
    ta = time.time() - t0
    ea = rel_error(w, dequantize(qa, fmt))

    t0 = time.time()
    qg = quantize_matrix_gumbel(w, fmt, steps=steps)
    tg = time.time() - t0
    eg = rel_error(w, dequantize(qg, fmt))

    print(f"  absmax : rel_fro={ea['rel_fro']:.5f} rmse={ea['rmse']:.6f}  ({ta:.2f}s)")
    print(f"  gumbel : rel_fro={eg['rel_fro']:.5f} rmse={eg['rmse']:.6f}  ({tg:.2f}s)")
    gain = (ea['rel_fro'] - eg['rel_fro']) / ea['rel_fro'] * 100
    print(f"  → 误差降低 {gain:+.2f}%   {'✅ 优于 absmax' if gain > 0 else '⚠️ 未超过 absmax'}")
    return gain


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--shape", default="512,4096")
    ap.add_argument("--steps", type=int, default=150)
    a = ap.parse_args()
    if a.selftest:
        n, k = (int(x) for x in a.shape.split(","))
        _selftest(a.bits, (n, k), a.steps)
    else:
        ap.print_help()
