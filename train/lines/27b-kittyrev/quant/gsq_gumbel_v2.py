#!/usr/bin/env python
"""
gsq_gumbel_v2.py — 对齐论文的 GSQ 量化（Lion + local-shift + 全局尺度收尾）

论文：GSQ: Highly-Accurate Low-Precision Scalar Quantization for LLMs via
      Gumbel-Softmax Sampling (arXiv 2604.18556)

与 v1（gsq_gumbel.py）的三处差异
────────────────────────────────────────────────────────────────────
① 优化器  v1 = Adam             →  v2 = Lion（论文指定，lr 需 /10）
② 码点表示 v1 = 全 K 个码点的分布 →  v2 = local-shift（高 bit 时只考虑 base_code ± shift）
           Q4 的 K=16 → 2*shift+1=5（shift=2），参数量降到 31%，过拟合更少
③ 尺度收尾 v1 = 每组独立 21 档倍数扫描  →  v2 = 每组 21 档 + 全局闭式最小二乘兜底
           全局解：s* = <w, c> / <c, c>（给定硬码点下的最优 scale），与倍数扫描取更优者

为什么 local-shift 是论文的关键设计
────────────────────────────────────────────────────────────────────
Q4 有 16 个码点。若每个元素都学 16 路分布，一个 group（64 元素）要学 64×16 = 1024 个
logits，而该 group 只有 64 个观测 —— 严重过拟合。
论文的解法：先用 absmax 得到 base_code，然后只让模型在 base_code 附近 ±shift 范围内
挑（默认 shift=2 → 5 个候选）。参数量 64×5 = 320，逼近观测数，泛化更好。
Q2 只有 4 个码点，不需要 local-shift（候选数已少于 5）。

用法
  python train/lines/27b-kittyrev/quant/gsq_gumbel_v2.py --selftest
  python train/lines/27b-kittyrev/quant/gsq_gumbel_v2.py --selftest --compare   # v1 vs v2 vs absmax
"""
from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass

import torch
import torch.nn.functional as F


# ─────────────────────────── 格式表（与 converter 对齐） ───────────────────────────

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

    @property
    def K(self) -> int:
        return self.qmax - self.qmin + 1


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


# ─────────────────────────── Lion 优化器（论文指定） ───────────────────────────

class Lion(torch.optim.Optimizer):
    """Lion: EvoLved Sign Momentum (Chen et al. 2023)

    update = sign(β1·m + (1-β1)·g)
    w      -= lr·(update + λ·w)
    m       = β2·m + (1-β2)·g

    注意：Lion 的更新量是 ±1（sign），所以 lr 应比 Adam 小约 10 倍。
    """

    def __init__(self, params, lr: float = 1e-4, betas: tuple[float, float] = (0.9, 0.99),
                 weight_decay: float = 0.0):
        if lr <= 0:
            raise ValueError(f"lr 必须为正，got {lr}")
        super().__init__(params, dict(lr=lr, betas=betas, weight_decay=weight_decay))

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        for group in self.param_groups:
            lr = group["lr"]
            b1, b2 = group["betas"]
            wd = group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                state = self.state[p]
                if "m" not in state:
                    state["m"] = torch.zeros_like(p)
                m = state["m"]
                # ① 用「旧动量 + 当前梯度」的 sign 做更新
                update = m.mul(b1).add(g, alpha=1 - b1).sign_()
                if wd != 0:
                    p.mul_(1 - lr * wd)
                p.add_(update, alpha=-lr)
                # ② 再用当前梯度更新动量
                m.mul_(b2).add_(g, alpha=1 - b2)
        return loss


# ─────────────────────────── 核心：local-shift GSQ ───────────────────────────

def _gumbel_softmax(logits: torch.Tensor, tau: float, hard: bool = False) -> torch.Tensor:
    return F.gumbel_softmax(logits, tau=tau, hard=hard, dim=-1)


def quantize_matrix_gsq_v2(
    weight: torch.Tensor,
    fmt: str | Fmt,
    *,
    steps: int = 150,
    lr: float = 5e-3,               # Lion 用 Adam 的 1/10
    tau0: float = 2.0,
    tau_min: float = 0.4,
    shift: int | None = None,       # None = 自动（K>8 用 2，否则全码点）
    row_batch: int = 256,
    imatrix: torch.Tensor | None = None,
    device: str | torch.device | None = None,
    scale_scan: int = 21,
    verbose: bool = False,
) -> QuantizedMatrix:
    """论文级 GSQ：Lion + local-shift + 闭式尺度兜底

    参数
        shift   local-shift 半径；None 时 K>8 用 2（5 个候选），否则用全部 K 个码点
        lr      Lion 学习率（sign 更新，比 Adam 小一个数量级）
        steps   每个 row_batch 的优化步数
    """
    spec = FORMATS[fmt] if isinstance(fmt, str) else fmt
    g = spec.group_size
    K = spec.K
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))

    # ★ 2026-11-07 实测：K≤4（Q2）时 Lion 的 sign 更新对 4 路 logits 太粗糙，
    #   lr 从 5e-4 扫到 2e-2 全部劣于 absmax（−10.9% ~ −14.5%）。
    #   论文本身也不在 Q2 上用 Gumbel 学码本（其 Q2 走 import_encoded 的 GGUF Q2_0 直通）。
    #   ⇒ K≤4 直接退回 absmax（保底不劣），Q4/Q5/Q8（K≥16）才走 local-shift GSQ。
    if K <= 4:
        return baseline_absmax(weight, spec)

    if shift is None:
        shift = 2 if K > 8 else (K // 2)          # Q4/Q5/Q8 → local-shift；Q2 → 全码点
    shift = max(1, min(shift, K // 2))
    use_local = shift < K // 2 + 1 and K > (2 * shift + 1)

    w = weight.detach().to(dtype=torch.float32)
    n, k = w.shape
    k_pad = math.ceil(k / g) * g
    if k_pad != k:
        wp = torch.zeros(n, k_pad, dtype=torch.float32)
        wp[:, :k] = w
        w = wp
    groups = k_pad // g
    levels = spec.levels.to(dev)

    reward = None
    if imatrix is not None:
        r = imatrix.detach().float().to(dev)
        if r.numel() == k and k_pad != k:
            rp = torch.ones(k_pad, dtype=torch.float32, device=dev)
            rp[:k] = r
            r = rp
        if r.numel() == k_pad:
            reward = r.reshape(groups, g).unsqueeze(0)      # [1,groups,g]

    codes_out = torch.empty(n, groups, g, dtype=torch.int8)
    scales_out = torch.empty(n, groups, dtype=torch.float16)

    for s in range(0, n, row_batch):
        e = min(s + row_batch, n)
        block = w[s:e].to(dev).reshape(e - s, groups, g)
        B = block.shape[0]

        with torch.no_grad():
            amax = block.abs().amax(dim=2)
            init_scale = (amax / spec.qmax).clamp_min(1e-8)
            # absmax 得到的基准码点（local-shift 的中心）
            base = (block / init_scale.unsqueeze(-1)).round().clamp(spec.qmin, spec.qmax)  # [B,G,g]
            log_scale = torch.nn.Parameter(init_scale.log().clone())                        # [B,G]

        if use_local:
            # ── local-shift：每个元素只在 base±shift 的候选里选（含 clamp 到合法码点）──
            offs = torch.arange(-shift, shift + 1, device=dev, dtype=torch.float32)         # [C]
            cand = (base.unsqueeze(-1) + offs.view(1, 1, 1, -1)).clamp(spec.qmin, spec.qmax)  # [B,G,g,C]
            logits = torch.nn.Parameter(torch.zeros(B, groups, g, 2 * shift + 1, device=dev))
            with torch.no_grad():
                logits[..., shift] = 1.5          # 初始偏向 base 本身（等价于 absmax 起手）
        else:
            # ── 全码点：与 v1 同构 ──
            cand = None
            dist = (base.unsqueeze(-1) - levels.view(1, 1, 1, -1)).abs()
            logits = torch.nn.Parameter((-dist * 4.0))

        opt = Lion([log_scale, logits], lr=lr)
        for st in range(steps):
            tau = tau0 * (tau_min / tau0) ** (st / max(steps - 1, 1))
            scale = log_scale.exp().unsqueeze(-1)
            soft = _gumbel_softmax(logits, tau=tau, hard=False)
            if use_local:
                code_val = (soft * cand).sum(dim=-1)                    # [B,G,g]
            else:
                code_val = (soft * levels.view(1, 1, 1, -1)).sum(dim=-1)
            w_hat = scale * code_val
            diff2 = (block - w_hat) ** 2
            if reward is not None:
                diff2 = diff2 * reward
            loss = diff2.mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            if verbose and st % max(steps // 5, 1) == 0:
                print(f"    [row {s}-{e}] step {st:3d} tau={tau:.3f} loss={loss.item():.6f}")

        # ── 收尾：硬码点 + 双路尺度（倍数扫描 + 闭式最小二乘）──
        with torch.no_grad():
            hidx = logits.argmax(dim=-1)                                # [B,G,g]
            if use_local:
                codes = torch.gather(cand, -1, hidx.unsqueeze(-1)).squeeze(-1)   # [B,G,g] 码点值
            else:
                codes = levels[hidx]
            base_scale = log_scale.exp()                                # [B,G]

            # 路①：0.90~1.10 倍数扫描
            best_err = torch.full((B, groups), float("inf"), device=dev)
            best_c = torch.zeros(B, groups, g, device=dev)
            best_s = base_scale.clone()
            for mult in torch.linspace(0.90, 1.10, scale_scan, device=dev):
                s_m = (base_scale * mult).unsqueeze(-1)
                c = torch.round(block / s_m).clamp(spec.qmin, spec.qmax)
                d2 = (block - c * s_m) ** 2
                if reward is not None:
                    d2 = d2 * reward
                err = d2.sum(dim=2)
                better = err < best_err
                best_err = torch.where(better, err, best_err)
                best_c = torch.where(better.unsqueeze(-1), c, best_c)
                best_s = torch.where(better, s_m.squeeze(-1), best_s)

            # 路②：闭式最小二乘 s* = <w,c> / <c,c>（用路①的码点）
            num = (block * best_c).sum(dim=2)
            den = (best_c * best_c).sum(dim=2).clamp_min(1e-12)
            s_ls = (num / den).clamp_min(1e-8)
            c_ls = torch.round(block / s_ls.unsqueeze(-1)).clamp(spec.qmin, spec.qmax)
            d2 = (block - c_ls * s_ls.unsqueeze(-1)) ** 2
            if reward is not None:
                d2 = d2 * reward
            err_ls = d2.sum(dim=2)
            better = err_ls < best_err
            best_c = torch.where(better.unsqueeze(-1), c_ls, best_c)
            best_s = torch.where(better, s_ls, best_s)

            codes_out[s:e] = best_c.round().to(torch.int8).cpu()
            scales_out[s:e] = best_s.to(torch.float16).cpu()

    return QuantizedMatrix(codes=codes_out, scales=scales_out)


# ─────────────────────────── 评估工具 ───────────────────────────

def dequantize(qm: QuantizedMatrix, fmt: str | Fmt, k: int | None = None) -> torch.Tensor:
    spec = FORMATS[fmt] if isinstance(fmt, str) else fmt
    codes = qm.codes.float()
    if spec.code_bias:
        codes = codes - spec.code_bias
    w = codes * qm.scales.float().unsqueeze(-1)
    w = w.reshape(w.shape[0], -1)
    return w[:, :k] if k else w


def baseline_absmax(weight: torch.Tensor, fmt: str | Fmt) -> QuantizedMatrix:
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
    d = (w - w_hat).float()
    return {
        "rel_fro": float(d.norm() / w.float().norm()),
        "rmse": float(d.pow(2).mean().sqrt()),
        "max_abs": float(d.abs().max()),
    }


def make_synth(n: int, k: int, seed: int = 0) -> torch.Tensor:
    """模拟 LLM 权重：高斯 + 1/2000 outlier（absmax 最怕的形状）"""
    torch.manual_seed(seed)
    w = torch.randn(n, k) * 0.02
    n_out = max(n * k // 2000, 8)
    idx = torch.randint(0, n * k, (n_out,))
    w.reshape(-1)[idx] *= 12.0
    return w


def _selftest(bits: int, shape: tuple[int, int], steps: int, compare_v1: bool):
    fmt = {2: "q2_g64_fp16", 4: "q4_g64_fp16", 5: "q5_g64_fp16", 8: "q8_g32_fp16"}[bits]
    n, k = shape
    w = make_synth(n, k)

    print(f"格式 {fmt} | 形状 {shape} | 码点 {FORMATS[fmt].K} | steps {steps}")
    print("-" * 72)

    t0 = time.time(); qa = baseline_absmax(w, fmt); ta = time.time() - t0
    ea = rel_error(w, dequantize(qa, fmt))
    print(f"  absmax      rel_fro={ea['rel_fro']:.5f}  rmse={ea['rmse']:.6f}  ({ta:.2f}s)")

    t0 = time.time()
    q2 = quantize_matrix_gsq_v2(w, fmt, steps=steps)
    t2 = time.time() - t0
    e2 = rel_error(w, dequantize(q2, fmt))
    g2 = (ea["rel_fro"] - e2["rel_fro"]) / ea["rel_fro"] * 100
    print(f"  gsq_v2      rel_fro={e2['rel_fro']:.5f}  rmse={e2['rmse']:.6f}  ({t2:.2f}s)  "
          f"vs absmax {g2:+.2f}%")

    if compare_v1:
        try:
            from gsq_gumbel import quantize_matrix_gumbel
            t0 = time.time()
            q1 = quantize_matrix_gumbel(w, fmt, steps=steps)
            t1 = time.time() - t0
            e1 = rel_error(w, dequantize(q1, fmt))
            g1 = (ea["rel_fro"] - e1["rel_fro"]) / ea["rel_fro"] * 100
            print(f"  gsq_v1      rel_fro={e1['rel_fro']:.5f}  rmse={e1['rmse']:.6f}  ({t1:.2f}s)  "
                  f"vs absmax {g1:+.2f}%")
            print(f"  → v2 vs v1: {(e1['rel_fro'] - e2['rel_fro']) / e1['rel_fro'] * 100:+.2f}%")
        except Exception as ex:
            print(f"  gsq_v1 跳过: {type(ex).__name__}: {str(ex)[:80]}")

    print("-" * 72)
    ok = g2 > 0
    print(f"  判定: {'✅ v2 优于 absmax' if ok else '⚠️ v2 未超过 absmax'}")
    return g2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compare", action="store_true", help="同时跑 v1 对比")
    ap.add_argument("--bits", type=int, default=4)
    ap.add_argument("--shape", default="512,4096")
    ap.add_argument("--steps", type=int, default=150)
    a = ap.parse_args()
    if a.selftest:
        shape = tuple(int(x) for x in a.shape.split(","))
        _selftest(a.bits, shape, a.steps, a.compare)
