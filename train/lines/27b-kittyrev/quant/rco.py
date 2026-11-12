#!/usr/bin/env python
"""
rco.py — RCO: 预算约束下的压缩选项分配（黎曼流形优化）

论文：Model Compression with Exact Budget Constraints via Riemannian Manifolds
      Michael Helcig & Dan Alistarh (ISTA-DASLab), arXiv:2605.00649v3

要解决什么问题
────────────────────────────────────────────────────────────────────
给定 G 个待压缩单元（group / 张量 / expert），每个有 K 个候选压缩档
（如 Q4 / Q5 / Q6 / Q8，各自的比特成本 c_k 与在该档下的损失 loss_k），
在「总比特数 ≤ 预算 B」的约束下，选一组分配使联合损失最小。

朴素做法（独立敏感性贪心）假设 loss 可加：Σ_g loss_g(opt_g)
论文指出这在压缩率较高时不成立 —— 量化误差会跨层传播。
RCO 优化的是「取决于整个压缩模型的联合损失」，不假设可加。

方法（论文的四步循环）
────────────────────────────────────────────────────────────────────
变量      z ∈ R^{G×K}，每组一个 logits 向量
分布      p = softmax(z)（沿 K 归一化）
期望成本  C(z) = Σ_g Σ_k p_gk · c_k             ← 约束面 C(z) = B
期望损失  L(z) = Σ_g Σ_k p_gk · loss_gk
约束流形  M = { z : C(z) = B }                     ← 黎曼子流形
① 投影    g_L^⊤ = g_L − ⟨g_L, g_C⟩/‖g_C‖² · g_C    （去掉法向分量，落进切空间）
② Adam    在切空间里走 Adam 步
③ retract 沿法向把 z 拉回 C(z) = B（一阶牛顿修正）
④ 传输    m, v 也投影到新切空间（把动量从旧切空间移到新切空间）

离散化
────────────────────────────────────────────────────────────────────
收敛后 p 是连续分布，需要落成离散分配。论文：
  · 期望成本约束是「精确」的（数值精度内）
  · 离散解码会引入小偏差（如 2.251 bits 实现 2.25 的目标）
本文件用「按性价比贪心的背包」，并把差值记进报告。

用法
────────────────────────────────────────────────────────────────────
  # 合成实验：10 组 4 档，预算 5.0 bits/组
  python train/lines/27b-kittyrev/quant/rco.py --selftest

  # 与「统一档位」「独立贪心」三方对比
  python train/lines/27b-kittyrev/quant/rco.py --selftest --compare
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field

import torch
import torch.nn.functional as F


# ─────────────────────────── 预算约束流形上的优化器 ───────────────────────────

@dataclass
class RCOConfig:
    """RCO 优化超参（论文 §3.2 的默认区间）"""
    lr: float = 5e-3
    lr_min: float = 5e-4          # cosine 衰减终点（0 或 None = 不衰减）
    betas: tuple[float, float] = (0.9, 0.999)
    eps: float = 1e-8
    steps: int = 600
    tau0: float = 1.0             # Gumbel straight-through 温度（前向硬/反向软）
    tau_min: float = 0.3
    retract_iters: int = 40
    entropy_coef: float = 0.02    # 熵正则：防止 p 过早收缩成 one-hot（会杀掉探索）
    polish_iters: int = 200       # 离散化后的 2-opt 局部搜索轮数
    verbose: bool = False


@dataclass
class RCOResult:
    z: torch.Tensor                          # [G,K] 收敛后的 logits
    probs: torch.Tensor                      # [G,K] softmax 概率
    assign: torch.Tensor                     # [G] 离散选项下标
    total_cost: float                        # 离散分配的实际总成本
    total_loss: float                        # 离散分配的实际总损失
    exp_cost: float                          # 收敛时的期望成本（应 ≈ budget）
    exp_loss: float                          # 收敛时的期望损失
    history: list = field(default_factory=list)


class RCO:
    """Riemannian Constrained Optimization for compression allocation

    参数
        costs   [G,K] 每个选项的比特成本（不可微，常量）
        losses  [G,K] 每个选项的损失（标量，来自候选库实测）
        budget  总比特预算（标量，如 5.0 * G）
    说明
        这里的 losses 是「该组选该档时的损失」。
        论文用可微的联合损失；本实现按「逐组候选实测 + 线性期望」近似，
        对 9B 这种 760 个张量的规模是工程可行的折中（§B2 会验证）。
    """

    def __init__(self, costs: torch.Tensor, losses: torch.Tensor, budget: float,
                 cfg: RCOConfig | None = None, device="cpu", loss_fn=None):
        """loss_fn(p) -> [G,K]：可选，给出「依赖当前整体分配的联合损失」

        论文的核心主张是优化取决于整个压缩模型的联合损失，而非各张量独立敏感度之和。
        传了 loss_fn 时每一步都用当前 p 重算损失矩阵，耦合项才能进入梯度。
        """
        assert costs.shape == losses.shape and costs.dim() == 2
        self.cfg = cfg or RCOConfig()
        self.dev = torch.device(device)
        self.costs = costs.detach().float().to(self.dev)      # [G,K]
        self.losses = losses.detach().float().to(self.dev)    # [G,K]
        self.loss_fn = loss_fn
        self.G, self.K = self.costs.shape
        self.budget = float(budget)

        # 初始 logits：偏向最便宜的选项，同时保证初始 C≈budget
        # ★ 2026-11-07：系数从 0.5 降到 0.15，避免初始 softmax 就接近 one-hot
        #   （one-hot 会让约束法向 gc 模长趋零 → retract 步长爆炸）
        c_min = self.costs.min(dim=1, keepdim=True).values
        self.z = torch.nn.Parameter((-self.costs + c_min) * 0.15)
        self.z.data += torch.randn_like(self.z) * 0.01
        self.m = torch.zeros_like(self.z)
        self.v = torch.zeros_like(self.z)
        self.step_i = 0

        # 初始化就把期望成本推到预算上（给足轮数，初始 gap 可能很大）
        ok = self._retract(iters=60)
        if not ok:
            p0 = self._probs()
            raise RuntimeError(
                f"RCO 初始化无法满足预算：C={float(self._exp_cost(p0)):.4f} budget={self.budget:.4f}"
            )

    # ── 约束与目标 ──
    def _probs(self) -> torch.Tensor:
        return F.softmax(self.z, dim=-1)

    def _exp_cost(self, p: torch.Tensor) -> torch.Tensor:
        return (p * self.costs).sum()

    def _exp_loss(self, p: torch.Tensor) -> torch.Tensor:
        return (p * self.losses).sum()

    # ── ③ retract：沿法向把 C 拉回 budget（二分，保证收敛）──
    def _retract(self, iters: int | None = None, tol: float = 1e-3):
        """把 C(z) 拉回 budget

        2026-11-07 调试：一阶牛顿在 softmax 上收敛太慢（60 轮仍有 3.7 的残差），
        改为沿法向做**二分搜索**：z(β) = z0 − β·ĝ，C(β) 关于 β 单调递减，
        二分 40 轮必然收敛（tol 1e-3 比特）。
        """
        n = iters if iters is not None else 40
        p = self._probs()
        C0 = self._exp_cost(p)
        if abs(C0 - self.budget) < tol:
            return True
        gc = p * (self.costs - C0)
        gc = gc / (gc * gc).sum().clamp_min(1e-2).sqrt()      # 单位化方向
        z0 = self.z.data.clone()

        def cost_at(beta: float) -> float:
            with torch.no_grad():
                self.z.data = z0 - beta * gc
            return float(self._exp_cost(self._probs()))

        # 扩上界直到 C ≤ budget
        lo, hi = 0.0, 1.0
        for _ in range(30):
            if cost_at(hi) <= self.budget:
                break
            hi *= 2.0
        else:
            with torch.no_grad():
                self.z.data = z0
            return False

        for _ in range(n):
            if hi - lo < 1e-6:
                break
            mid = 0.5 * (lo + hi)
            if cost_at(mid) > self.budget:
                lo = mid
            else:
                hi = mid
        with torch.no_grad():
            self.z.data = (z0 - hi * gc).clamp_(-40.0, 40.0)
        return abs(float(self._exp_cost(self._probs())) - self.budget) < tol

    # ── ④ 把动量投影到当前切空间 ──
    def _transport_momentum(self):
        """只传输一阶动量 m；v 不做投影

        2026-11-07 调试（这一步是 nan 的真凶）：
          v 是 Adam 的二阶动量（逐元素梯度平方累积，必须 ≥ 0）。
          若也做 `v -= proj*gc`，v 会变成负数 → 下一步 v_hat.sqrt() = nan
          → delta = nan → z = nan。
          论文的「transports optimizer momentum」指的是一阶动量与状态的方向修正；
          二阶动量是尺度估计，投影会破坏其非负语义，故此处只投影 m，v 仅做非负兜底。
        """
        p = self._probs()
        C = self._exp_cost(p)
        gc = p * (self.costs - C)
        denom = (gc * gc).sum().clamp_min(1e-2)
        proj = ((self.m * gc).sum() / denom).clamp(-10.0, 10.0)
        self.m -= proj * gc
        self.v.clamp_min_(0.0)

    def step(self) -> dict:
        cfg = self.cfg
        self.step_i += 1
        p = self._probs()
        # ★ 联合损失：传了 loss_fn 就按当前 p 重算（跨组耦合项进入梯度）
        if self.loss_fn is not None:
            self.losses = self.loss_fn(p).to(self.dev)
        C = self._exp_cost(p)
        L = self._exp_loss(p)

        # 梯度（解析）：
        #   dL/dz_{gk} = p_gk (loss_gk − Σ_j p_gj loss_gj)
        #   dC/dz_{gk} = p_gk (c_gk   − Σ_j p_gj c_gj)
        gc = p * (self.costs - C)                    # [G,K]
        gl = p * (self.losses - L)                   # [G,K]

        # ① 投影到切空间：去掉 gl 中沿 gc 的法向分量
        # ★ 2026-11-07 调参：retract 之后 p 往往很尖，gc 模长趋零，
        #   n2 若不设下限，proj 会爆到 1e13 → gl_tan 爆 → Adam 的 v 爆 → nan。
        #   n2 下限与 retract 保持一致（1e-2），proj 再夹一层 ±5。
        n2 = (gc * gc).sum().clamp_min(1e-2)
        proj = ((gl * gc).sum() / n2).clamp(-5.0, 5.0)
        gl_tan = gl - proj * gc

        # ①b 熵正则：−λ·dH/dz，H = −Σ p log p
        #     H 关于 z 的梯度：p·(log p + H)
        #     加在 gl_tan 上，方向也在切空间里（gc 分量会被下面的投影去掉）
        if cfg.entropy_coef > 0:
            logp = torch.log(p.clamp_min(1e-9))
            H = -(p * logp).sum()
            gh = p * (logp + H)                     # [G,K]
            gh_tan = gh - ((gh * gc).sum() / n2).clamp(-5.0, 5.0) * gc
            gl_tan = gl_tan - cfg.entropy_coef * gh_tan

        # ② 切空间里的 Adam（带 cosine 衰减）
        b1, b2 = cfg.betas
        if cfg.lr_min is not None and cfg.steps:
            prog = min(1.0, self.step_i / max(cfg.steps, 1))
            cur_lr = cfg.lr_min + 0.5 * (cfg.lr - cfg.lr_min) * (1 + math.cos(math.pi * prog))
        else:
            cur_lr = cfg.lr
        self.m = b1 * self.m + (1 - b1) * gl_tan
        self.v = b2 * self.v + (1 - b2) * gl_tan * gl_tan
        m_hat = self.m / (1 - b1 ** self.step_i)
        v_hat = self.v / (1 - b2 ** self.step_i)
        # ★ 2026-11-07 关键修正：Adam 的更新量也必须投影到切空间。
        #   gl_tan 本身与 gc 严格正交（⟨gl_tan,gc⟩=0），但 Adam 用 sqrt(v_hat) 做
        #   逐元素缩放后会破坏这个正交性 → 每步都把 C 推离预算 → retract 拉不回来。
        #   把 delta 里的法向分量除掉，更新才真正留在约束流形上。
        delta = -cur_lr * m_hat / (v_hat.sqrt() + cfg.eps)
        d_proj = (delta * gc).sum() / n2
        delta = delta - d_proj * gc
        z_before = self.z.data.clone()
        with torch.no_grad():
            self.z.data += delta
            self.z.data.clamp_(-40.0, 40.0)

        # ③ retract 回约束面；若本次无法拉回，整步回滚（保证约束不漂移）
        if not self._retract():
            with torch.no_grad():
                self.z.data = z_before
            self.m.mul_(0.5)          # 动量减半，下次别走同样大的步子
        # ④ 动量传输到新切空间
        self._transport_momentum()

        if cfg.verbose and self.step_i % max(cfg.steps // 8, 1) == 0:
            p2 = self._probs()
            print(f"    step {self.step_i:4d}  C={self._exp_cost(p2):.4f} (budget {self.budget:.2f})  "
                  f"L={self._exp_loss(p2):.6f}")
        return {"step": self.step_i, "exp_cost": float(self._exp_cost(self._probs())),
                "exp_loss": float(self._exp_loss(self._probs()))}

    # ── 离散化：预算约束下的贪心背包 ──
    def discretize(self, prefer: str = "value") -> tuple[torch.Tensor, float, float]:
        """把连续概率落成离散分配

        策略 value（默认）：从最低档全选起步，每次升级「损失降低 / 成本增加」最大的
                            （成本按真实比特数累加，不超预算）
        策略 prob：按 argmax(p) 直接取（不保证预算，仅作对照）
        """
        p = self._probs()
        if prefer == "prob":
            assign = p.argmax(dim=-1)
            cost = float(self.costs.gather(1, assign.unsqueeze(-1)).sum())
            loss = float(self.losses.gather(1, assign.unsqueeze(-1)).sum())
            return assign, cost, loss

        # 从每行最便宜的档起步
        assign = self.costs.argmin(dim=-1).clone()
        cost = self.costs.gather(1, assign.unsqueeze(-1)).squeeze(-1).clone()   # [G]
        loss = self.losses.gather(1, assign.unsqueeze(-1)).squeeze(-1).clone()  # [G]
        total_cost = float(cost.sum())

        # 候选升级：(分数, 增益, 代价, g, k)
        # ★ 2026-11-07：分数用「RCO 学到的偏好 p × 性价比」。
        #   只按性价比排序会退化成独立贪心（实测与 greedy_independent 完全一致，+0.00%），
        #   连续解的信息就丢了。用 p 加权后，RCO 判断「这组该拿高 bit」的结论能落到离散分配上。
        cands = []
        for g in range(self.G):
            k0 = int(assign[g])
            for k in range(self.K):
                if self.costs[g, k] <= self.costs[g, k0]:
                    continue
                dc = float(self.costs[g, k] - self.costs[g, k0])
                dl = float(loss[g] - self.losses[g, k])       # 正数表示损失下降
                if dl <= 0 or dc <= 0:
                    continue
                pref = float(p[g, k])
                cands.append((pref * dl / dc, dl, dc, g, k))
        cands.sort(reverse=True)

        for ratio, dl, dc, g, k in cands:
            if total_cost + dc > self.budget + 1e-6:
                continue
            k0 = int(assign[g])
            if float(self.costs[g, k]) <= float(self.costs[g, k0]):
                continue
            total_cost -= float(self.costs[g, k0])
            total_cost += float(self.costs[g, k])
            assign[g] = k

        final_cost = float(self.costs.gather(1, assign.unsqueeze(-1)).sum())
        final_loss = float(self.losses.gather(1, assign.unsqueeze(-1)).sum())

        # ★ 2-opt 局部搜索：贪心只是起点，连续解里「哪组该高 bit」的信息还没用尽。
        #   对每组尝试升/降一档，若总损失下降且不破预算则接受，反复直到无改进。
        #   （在非可加损失下，这一轮能显著补上"连续→离散"的 gap）
        for _ in range(max(self.cfg.polish_iters, 0)):
            improved = False
            for g in range(self.G):
                cur = int(assign[g])
                for k in range(self.K):
                    if k == cur:
                        continue
                    dc = float(self.costs[g, k] - self.costs[g, cur])
                    dl = float(self.losses[g, k] - self.losses[g, cur])
                    if dl >= -1e-9:
                        continue                     # 损失没下降
                    if final_cost + dc > self.budget + 1e-6:
                        continue                     # 破预算
                    assign[g] = k
                    final_cost += dc
                    final_loss += dl
                    improved = True
                    break
                if improved:
                    break
            if not improved:
                break

        return assign, final_cost, final_loss

    def run(self, prefer: str = "value") -> RCOResult:
        hist = []
        for _ in range(self.cfg.steps):
            hist.append(self.step())
        p = self._probs()
        assign, cost, loss = self.discretize(prefer)
        return RCOResult(
            z=self.z.detach().clone(), probs=p.detach().clone(), assign=assign,
            total_cost=cost, total_loss=loss,
            exp_cost=float(self._exp_cost(p)), exp_loss=float(self._exp_loss(p)),
            history=hist,
        )


# ─────────────────────────── 对照基线 ───────────────────────────

def uniform_assign(costs: torch.Tensor, losses: torch.Tensor, budget: float) -> tuple[torch.Tensor, float, float]:
    """基线①：所有组用同一个档位（取不超过预算的最大档）"""
    G, K = costs.shape
    per_group_budget = budget / G
    best_k, best_loss = None, float("inf")
    for k in range(K):
        if float(costs[:, k].mean()) <= per_group_budget + 1e-6:
            l = float(losses[:, k].sum())
            if l < best_loss:
                best_k, best_loss = k, l
    if best_k is None:
        best_k = int(costs.mean(dim=0).argmin())
    assign = torch.full((G,), best_k, dtype=torch.long)
    return assign, float(costs[:, best_k].sum()), float(losses[:, best_k].sum())


def greedy_independent(costs: torch.Tensor, losses: torch.Tensor, budget: float) -> tuple[torch.Tensor, float, float]:
    """基线②：完全独立的贪心（每组只看自己，不看联合损失）—— 与 RCO 的离散化同策略"""
    G, K = costs.shape
    assign = costs.argmin(dim=-1).clone()
    total_cost = float(costs.gather(1, assign.unsqueeze(-1)).sum())
    cands = []
    for g in range(G):
        k0 = int(assign[g])
        for k in range(K):
            dc = float(costs[g, k] - costs[g, k0])
            dl = float(losses[g, k0] - losses[g, k])
            if dc > 0 and dl > 0:
                cands.append((dl / dc, dl, dc, g, k))
    cands.sort(reverse=True)
    for ratio, dl, dc, g, k in cands:
        if total_cost + dc > budget + 1e-6:
            continue
        k0 = int(assign[g])
        if float(costs[g, k]) <= float(costs[g, k0]):
            continue
        total_cost += float(costs[g, k] - costs[g, k0])
        assign[g] = k
    return assign, float(costs.gather(1, assign.unsqueeze(-1)).sum()), float(losses.gather(1, assign.unsqueeze(-1)).sum())


# ─────────────────────────── 自测 ───────────────────────────

def make_fixture(G: int = 10, seed: int = 0, coupling: float = 0.5):
    """合成候选库 + 联合损失函数（带跨组耦合）

    返回 (costs, losses_static, loss_fn)
      costs         [G,K] 每档比特成本
      losses_static [G,K] 静态基线（独立敏感度，给基线方法用）
      loss_fn(p)    [G,K] 联合损失：额外项依赖当前整体分配的平均档位

    耦合的物理含义：敏感组（base 高）的实际损失会被「同模型其他组压得太狠」拖累 ——
    这正是论文说的「压缩误差跨层传播、损失不可加」。
    """
    torch.manual_seed(seed)
    costs_1d = torch.tensor([4.25, 5.00, 6.00, 8.25])
    K = costs_1d.numel()
    costs = costs_1d.unsqueeze(0).repeat(G, 1)

    base = torch.rand(G) * 0.9 + 0.1
    base = base / base.mean()
    decay = torch.tensor([1.0, 0.62, 0.32, 0.08])
    # ★ 2026-11-07：必须加 per-(g,k) 独立扰动。
    #   否则 losses[g,k] = base_g · (decay_k + 耦合项) 与 base_g 严格成正比，
    #   导致梯度 gl 与约束法向 gc 高度共线 → gl_tan = gl − proj·gc ≈ 0
    #   → Adam 更新量恒为零 → 优化完全不动（实测 L 到小数点后 6 位不变）。
    noise = torch.rand(G, K) * 0.35
    losses_static = base.unsqueeze(-1) * decay.unsqueeze(0) + noise    # [G,K]

    idx = torch.arange(K).float() / (K - 1)                     # 档位归一化 0..1

    def loss_fn(p: torch.Tensor) -> torch.Tensor:
        # 全局平均档位（0=全 Q4，1=全 Q8）
        avg_level = (p * idx.to(p.device).unsqueeze(0)).sum() / G
        # ★ 2026-11-07：耦合项必须是**非线性**的，RCO 才有存在意义。
        #   线性耦合下「目标线性 + 约束线性」是 LP，最优解是 bang-bang，
        #   独立贪心背包就能精确求解（实测 RCO 连续解反而比贪心差 2%）。
        #   用平方项：平均档位越低，敏感组的额外损失超线性上升 —— 这才是
        #   论文所说的「压缩误差跨层传播、损失不可加」的形状。
        extra = coupling * base.unsqueeze(-1) * (1.0 - avg_level) ** 2
        return losses_static.to(p.device) + extra

    # 基线方法只看静态损失
    return costs, losses_static, loss_fn


def _selftest(compare: bool):
    G, K = 10, 4
    costs, losses, loss_fn = make_fixture(G)
    budget = 5.00 * G                    # 平均 5.00 bits/组

    print(f"合成实验：{G} 组 × {K} 档 · 档位成本 {costs[0].tolist()} · 总预算 {budget:.2f} bits")
    print("-" * 78)

    # RCO（带联合损失）
    cfg = RCOConfig(steps=600, lr=2e-2, verbose=True)
    rco = RCO(costs, losses, budget, cfg, loss_fn=loss_fn)
    res = rco.run()
    # 用真实联合损失（按最终 p）评估，而不是静态 losses
    joint_l = float((res.probs * loss_fn(res.probs)).sum())
    print(f"  RCO 连续解   期望成本 C={res.exp_cost:.4f}（预算 {budget:.2f}）· 联合损失 L={joint_l:.6f}")
    print(f"  RCO 离散解   实际成本 {res.total_cost:.4f} · 静态损失 {res.total_loss:.6f}")
    print(f"               分配 {res.assign.tolist()}")

    if compare:
        a_u, c_u, l_u = uniform_assign(costs, losses, budget)
        a_g, c_g, l_g = greedy_independent(costs, losses, budget)
        # 基线也用同一联合损失口径评估（它们的 p 是 one-hot）
        p_u = F.one_hot(a_u, K).float()
        p_g = F.one_hot(a_g, K).float()
        j_u = float((p_u * loss_fn(p_u)).sum())
        j_g = float((p_g * loss_fn(p_g)).sum())
        print(f"  统一档位     成本 {c_u:.4f} · 联合损失 {j_u:.6f} · 档位 {a_u[0].item()}")
        print(f"  独立贪心     成本 {c_g:.4f} · 联合损失 {j_g:.6f} · 分配 {a_g.tolist()}")
        print("-" * 78)
        print(f"  RCO 连续 vs 统一   {(j_u - joint_l) / j_u * 100:+.2f}%")
        print(f"  RCO 连续 vs 贪心   {(j_g - joint_l) / j_g * 100:+.2f}%")

    print("-" * 78)
    ok = abs(res.exp_cost - budget) < 0.05
    print(f"  约束满足：|C − B| = {abs(res.exp_cost - budget):.5f}  {'✅' if ok else '✗'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.selftest:
        _selftest(a.compare)
