#!/usr/bin/env python
"""诊断 B4 反直觉结果：为什么统一 q5 的损失比贪心/RCO 还低？

两件事分开查：
  A. 能力面：各组「敏感度」是否真的有差异（q5/q4 比值是否一致）
     —— 若一致，统一档位就是最优解，任何混合分配都是负优化，RCO 无用
  B. 实现面：greedy_independent 的选择过程是否走了错误路径
     —— 逐条打印候选的性价比排序与预算消耗
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402

CAND = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out", "b3-candidates.json")
TAGS = ["q4", "q5", "q6", "q8"]


def main():
    d = json.load(open(CAND, encoding="utf-8"))
    bit_cost = d["config"]["bits"]
    groups = d["groups"]
    G, K = len(groups), len(TAGS)

    elems = [g["shape"][0] * g["shape"][1] * g["n_tensors"] for g in groups]
    total = sum(elems)

    print("=" * 96)
    print("A. 敏感度差异检验：各档相对 q4 的误差比值")
    print("=" * 96)
    print(f"{'shape':>16} {'元素M':>8} {'权重%':>6} {'q4':>9} {'q5':>9} {'q6':>9} {'q8':>9} "
          f"{'q5/q4':>7} {'q8/q4':>7}")
    print("-" * 96)
    r5, r8 = [], []
    for gi, g in enumerate(groups):
        c = g["cands"]
        ratio5 = c["q5"] / c["q4"]
        ratio8 = c["q8"] / c["q4"]
        r5.append(ratio5)
        r8.append(ratio8)
        print(f"{str(g['shape']):>16} {elems[gi]/1e6:>8.1f} {elems[gi]/total*100:>6.2f} "
              f"{c['q4']:>9.5f} {c['q5']:>9.5f} {c['q6']:>9.5f} {c['q8']:>9.5f} "
              f"{ratio5:>7.4f} {ratio8:>7.4f}")
    print("-" * 96)

    import statistics
    print(f"q5/q4 比值: min={min(r5):.4f} max={max(r5):.4f} "
          f"median={statistics.median(r5):.4f} stdev={statistics.stdev(r5):.4f} "
          f"相对离散度={statistics.stdev(r5)/statistics.median(r5)*100:.2f}%")
    print(f"q8/q4 比值: min={min(r8):.4f} max={max(r8):.4f} "
          f"median={statistics.median(r8):.4f} stdev={statistics.stdev(r8):.4f} "
          f"相对离散度={statistics.stdev(r8)/statistics.median(r8)*100:.2f}%")
    print()
    if statistics.stdev(r5) / statistics.median(r5) < 0.10:
        print("  ★ 结论：各组的降档误差放大倍数差异 <10% ⇒ 敏感度基本一致")
        print("    ⇒ 统一档位就是最优解；任何「牺牲大组保小组」的分配都是负优化")
        print("    ⇒ 这不是 bug，是数据本身没有可供分配的信息量")
    else:
        print("  ⇒ 各组敏感度有实质差异，混合分配应该有收益；问题可能在实现")

    # ── B. 贪心路径追踪 ──
    print()
    print("=" * 96)
    print("B. greedy_independent 选择过程追踪")
    print("=" * 96)
    costs = torch.zeros(G, K)
    losses = torch.zeros(G, K)
    for gi, g in enumerate(groups):
        w = elems[gi] / total
        for ki, tag in enumerate(TAGS):
            costs[gi, ki] = w * bit_cost[tag]
            losses[gi, ki] = elems[gi] * (g["cands"][tag] ** 2)

    budget = 5.0
    assign = costs.argmin(dim=-1).clone()
    total_cost = float(costs.gather(1, assign.unsqueeze(-1)).sum())
    print(f"起点：全 {TAGS[assign[0].item()]} · 成本 {total_cost:.4f} · 预算 {budget:.4f} · "
          f"余量 {budget-total_cost:.4f}")
    print()

    cands = []
    for g in range(G):
        k0 = int(assign[g])
        for k in range(K):
            dc = float(costs[g, k] - costs[g, k0])
            dl = float(losses[g, k0] - losses[g, k])
            if dc > 0 and dl > 0:
                cands.append((dl / dc, dl, dc, g, k))
    cands.sort(reverse=True)
    print(f"候选数 {len(cands)} · 按性价比(dl/dc)降序前 12 条：")
    print(f"{'rank':>4} {'shape':>16} {'升级':>7} {'dl(误差降)':>13} {'dc(成本)':>10} {'性价比':>12} {'累计成本':>10}")
    print("-" * 96)
    cum = total_cost
    shown = 0
    for ratio, dl, dc, g, k in cands:
        k0 = int(assign[g])
        if float(costs[g, k]) <= float(costs[g, k0]):
            continue
        ok = cum + float(costs[g, k] - costs[g, k0]) <= budget + 1e-6
        if shown < 12:
            print(f"{shown+1:>4} {str(groups[g]['shape']):>16} "
                  f"{TAGS[k0]}→{TAGS[k]:>2} {dl/1e6:>13.2f} {dc:>10.4f} {ratio/1e6:>12.2f} "
                  f"{'✓' if ok else '✗超预算'}")
            shown += 1
        if ok:
            cum += float(costs[g, k] - costs[g, k0])
            assign[g] = k

    print("-" * 96)
    print(f"贪心终态：成本 {cum:.4f} · 分配 {[TAGS[i] for i in assign.tolist()]}")

    # 对比统一 q5
    uni_cost = float(costs[:, 1].sum())
    uni_loss = float(losses[:, 1].sum())
    gre_loss = float(losses.gather(1, assign.unsqueeze(-1)).sum())
    print(f"统一 q5：成本 {uni_cost:.4f} · 加权损失 {uni_loss/1e6:.2f}M")
    print(f"贪心   ：成本 {cum:.4f} · 加权损失 {gre_loss/1e6:.2f}M")
    print(f"差值   ：贪心损失 {((gre_loss-uni_loss)/uni_loss*100):+.2f}% vs 统一")


if __name__ == "__main__":
    main()
