#!/usr/bin/env python
"""B4：读 B3 候选库 → 构造 costs/losses → 跑 RCO 搜索位宽分配

输入
    out/b3-candidates.json（B3 产物：每组形状的 Q4/Q5/Q6/Q8 实测相对重构误差）

输出
    out/b4-allocation.json（每组的档位分配 + 预期总误差 + 实际成本）

关键设计
    · G = 候选组数（12 组），K = 4 档
    · 成本 costs[g][k] = 该组元素数 × 每权重比特数（总比特）
    · 损失 losses[g][k] = 该组元素数 × rel_fro²（加权平方误差，近似总误差能量）
      用元素数加权是对的：大张量的量化误差对模型输出影响更大
    · 预算 budget = 可量化总元素 × 目标 bits/weight
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402

from rco import RCO, RCOConfig, greedy_independent, uniform_assign  # noqa: E402

CAND = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out", "b3-candidates.json")
OUT = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out", "b4-allocation.json")

TAGS = ["q4", "q5", "q6", "q8"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", default=CAND)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--target-bits", type=float, default=5.0, help="目标 bits/weight")
    ap.add_argument("--lr", type=float, default=1e-2)
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--entropy", type=float, default=0.0)
    a = ap.parse_args()

    d = json.load(open(a.cand, encoding="utf-8"))
    bit_cost = d["config"]["bits"]                      # {"q4":4.25, ...}
    groups = d["groups"]
    G, K = len(groups), len(TAGS)

    # 构造 costs / losses
    # ★ 关键：costs 必须归一化到 bits/weight 量级（否则总量 1e10，retract 的
    #   二分上界靠 hi*=2 只能扩到 2^30，够不着 → 初始化就抛"无法满足预算"）
    #   归一化方式：每组成本 = (该组元素数 / 总元素数) × 每权重比特
    #   ⇒ Σ_g costs[g,k] = 平均每权重比特数，量级 O(5)
    costs = torch.zeros(G, K)
    losses = torch.zeros(G, K)
    elems = []
    for g in groups:
        shp = g["shape"]
        elems.append(shp[0] * shp[1] * g["n_tensors"])
    elems_t = torch.tensor(elems, dtype=torch.float64)
    total_elem = float(elems_t.sum())
    for gi, g in enumerate(groups):
        w = elems[gi] / total_elem                      # 该组权重占比
        for ki, tag in enumerate(TAGS):
            costs[gi, ki] = w * bit_cost[tag]           # 归一化成本（bits/weight 口径）
            r = g["cands"].get(tag)
            # 损失：元素数 × rel_fro²（误差能量，量级大但不进约束，无妨）
            losses[gi, ki] = elems[gi] * (r ** 2) if r is not None else 1e18
    budget = a.target_bits                              # 直接就是 bits/weight

    print("=" * 84)
    print(f"B4 位宽分配搜索 · 目标 {a.target_bits} bits/weight")
    print("=" * 84)
    print(f"{'shape':>16} {'张量':>5} {'元素M':>8} {'q4':>9} {'q5':>9} {'q6':>9} {'q8':>9}")
    print("-" * 84)
    for gi, g in enumerate(groups):
        c = g["cands"]
        print(f"{str(g['shape']):>16} {g['n_tensors']:>5} {elems[gi]/1e6:>8.1f} "
              f"{c['q4']:>9.5f} {c['q5']:>9.5f} {c['q6']:>9.5f} {c['q8']:>9.5f}")
    print("-" * 84)
    print(f"可量化总元素 {total_elem/1e6:.1f}M · 预算 {budget:.4f} bits/weight")

    def joint_loss(p: torch.Tensor) -> torch.Tensor:
        """联合损失：这里仍是逐组可加（真实模型应换成需前向传播的不可加损失）
        但至少用真实测量误差，不再是合成 fixture。"""
        return losses.to(p.device)

    def total_loss_of(p_or_assign, is_assign=True):
        if is_assign:
            p = F.one_hot(p_or_assign, K).float()
        else:
            p = p_or_assign
        L = joint_loss(p)
        return float((p * L).sum())

    print()
    print("=== 三方对比 ===")
    a_u, c_u, _ = uniform_assign(costs, losses, budget)
    j_u = total_loss_of(a_u)
    print(f"统一档位     成本 {c_u:>8.4f}  损失能量 {j_u:.6e}  档位 {TAGS[a_u[0].item()]}")

    a_g, c_g, _ = greedy_independent(costs, losses, budget)
    j_g = total_loss_of(a_g)
    print(f"独立贪心     成本 {c_g:>8.4f}  损失能量 {j_g:.6e}")

    cfg = RCOConfig(steps=a.steps, lr=a.lr, entropy_coef=a.entropy, polish_iters=500)
    rco = RCO(costs, losses, budget, cfg, loss_fn=joint_loss)
    res = rco.run()
    j_r_cont = total_loss_of(res.probs, is_assign=False)
    j_r_disc = total_loss_of(res.assign)
    print(f"RCO 连续解   成本 {res.exp_cost:>8.4f}  损失能量 {j_r_cont:.6e}")
    print(f"RCO 离散解   成本 {res.total_cost:>8.4f}  损失能量 {j_r_disc:.6e}")
    print()
    print(f"RCO连续 vs 统一: {(j_u-j_r_cont)/j_u*100:+.2f}%")
    print(f"RCO连续 vs 贪心: {(j_g-j_r_cont)/j_g*100:+.2f}%")
    print(f"RCO离散 vs 统一: {(j_u-j_r_disc)/j_u*100:+.2f}%")
    print(f"RCO离散 vs 贪心: {(j_g-j_r_disc)/j_g*100:+.2f}%")

    print()
    print("=== 分配明细 ===")
    print(f"{'shape':>16} {'张量':>5} {'元素M':>8} {'统一':>6} {'贪心':>6} {'RCO':>6}")
    print("-" * 60)
    for gi, g in enumerate(groups):
        print(f"{str(g['shape']):>16} {g['n_tensors']:>5} {elems[gi]/1e6:>8.1f} "
              f"{TAGS[a_u[gi].item()]:>6} {TAGS[a_g[gi].item()]:>6} {TAGS[res.assign[gi].item()]:>6}")

    payload = {
        "target_bits": a.target_bits,
        "total_elems": total_elem,
        "budget": budget,
        "uniform": {"assign": [TAGS[i] for i in a_u.tolist()], "cost": c_u, "loss": j_u},
        "greedy": {"assign": [TAGS[i] for i in a_g.tolist()], "cost": c_g, "loss": j_g},
        "rco": {"assign": [TAGS[i] for i in res.assign.tolist()],
                "cost": res.total_cost, "loss": j_r_disc,
                "exp_cost": res.exp_cost, "exp_loss": j_r_cont},
        "groups": [{"shape": g["shape"], "n_tensors": g["n_tensors"],
                    "elems": float(elems[gi]),
                    "rco_tag": TAGS[res.assign[gi].item()],
                    "tensor_names": g["tensor_names"]} for gi, g in enumerate(groups)],
    }
    json.dump(payload, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[OK] → {a.out}")


if __name__ == "__main__":
    main()
