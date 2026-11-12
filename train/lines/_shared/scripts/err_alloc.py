#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""err_alloc.py —— 用实测误差做混合精度分配（GSQ 目标函数的可执行版分配器）

输入：err_sweep.py 产出的 stats.jsonl（每张量 × 每候选类型的 实测字节 / 加权 MSE）
输出：llama-quantize 的 --tensor-type-file 表 + 分配报告

目标（GSQ 式 (1) 的离散版）：
    min  Σ_t  Err_t(type_t)          s.t.  Σ_t  Bytes_t(type_t) ≤ BUDGET
    Err_t = wmse_t × n_elem          （wmse 是每元素加权均方误差）

做法：每个张量先取最省字节类型作基线，再按 Δerr/Δbytes 密度做贪心升级
      （类型链单调，贪心对凸链近似最优；相比按 BPP 表猜，这里全是实测数）

结构保护（与 gsq_rco_plan.py 同规则，不参与优化，强制高精度）：
    ssm_*/A_log/dt_bias/conv1d/*.bias → Q8_0 ； *.norm → Q6_K
    output/lm_head → Q6_K ； token_embd → Q2_K ； mtp.* → Q8_0

用法：
  python err_alloc.py --stats stats.jsonl --budget 10.28e9 \
      --types IQ2_S,Q2_K,IQ3_S,IQ4_XS --out plan.txt --report report.md
  # 对照现有分配（给已存在的 types 表算预测误差）
  python err_alloc.py ... --compare local-pack/gen3_1q/gen3_1q-types.txt
"""
import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

# 每元素字节（用于没被 sweep 覆盖的张量：embed / 1D 保护项）
BPP = {"IQ2_XXS": 2.06, "Q2_0": 2.25, "IQ2_XS": 2.31, "IQ2_S": 2.50, "Q2_K": 2.63,
       "IQ3_XXS": 3.06, "IQ3_XS": 3.30, "IQ3_S": 3.44, "Q3_K": 3.44, "IQ4_XS": 4.25,
       "Q4_K": 4.50, "Q4_0": 4.50, "Q5_K": 5.50, "Q5_0": 5.50, "Q6_K": 6.56, "Q8_0": 8.50}

RANK_PROTECT = [
    (r"\.ssm_alpha\.weight$", "Q8_0"), (r"\.ssm_beta\.weight$", "Q8_0"),
    (r"\.in_proj_a\.weight$", "Q8_0"), (r"\.in_proj_b\.weight$", "Q8_0"),
    (r"\.A_log$", "Q8_0"), (r"\.ssm_a$", "Q8_0"), (r"\.ssm_conv1d\.weight$", "Q8_0"),
    (r"\.dt_bias$", "Q8_0"), (r"\.conv1d\.weight$", "Q8_0"),
    (r"norm\.weight$", "Q6_K"), (r"\.bias$", "Q8_0"),
]
CHANNEL_PROTECT = [
    (r"^output\.weight$", "Q6_K"), (r"^token_embd\.weight$", "Q2_K"),
    (r"lm_head\.weight$", "Q6_K"), (r"visual\.merger", "Q6_K"), (r"^mtp\.", "Q8_0"),
]


def protect(name):
    for pat, ty in RANK_PROTECT + CHANNEL_PROTECT:
        if re.search(pat, name):
            return ty
    return None


def load_stats(path):
    """{tensor: {type: (bytes, n_elem, wmse)}}；wmse 取多次出现的中位数（多臂只跑一次，此处幂等）"""
    acc = defaultdict(lambda: defaultdict(list))
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        acc[d["tensor"]][d["type"]].append((d["bytes_total"], d["n_elem"], d["wmse"]))
    out = {}
    for t, per in acc.items():
        out[t] = {}
        for ty, vals in per.items():
            bs = sorted(v[0] for v in vals)
            es = sorted(v[2] for v in vals)
            out[t][ty] = (bs[len(bs) // 2], es[len(es) // 2], vals[0][1])
    return out


def ladders(stats, types):
    """每张量：按字节升序的 Pareto 链 [(bytes, err_total, type)]"""
    out = {}
    for t, per in stats.items():
        pts = []
        for ty in types:
            if ty not in per:
                continue
            b, e, n = per[ty]
            pts.append((b, e * n, ty))
        if not pts:
            continue
        pts.sort()
        chain, best = [], math.inf
        for b, e, ty in pts:
            if e < best:
                chain.append((b, e, ty))
                best = e
        out[t] = chain
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", required=True)
    ap.add_argument("--budget", type=float, default=10.28e9)
    ap.add_argument("--types", default="IQ2_S,Q2_K,IQ3_S,IQ4_XS")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default="")
    ap.add_argument("--compare", default="", help="已有 types 表，算它的预测误差做对照")
    ap.add_argument("--n-elem-total", type=float, default=0.0,
                    help="全部可量化张量参数量（用于把误差归一成人均）")
    a = ap.parse_args()

    types = [t.strip() for t in a.types.split(",") if t.strip()]
    stats = load_stats(a.stats)
    chains = ladders(stats, types)
    print(f"[in] 张量 {len(stats)}，有链 {len(chains)}，类型 {types}")

    # 1) 固定项：保护张量与未 sweep 覆盖的张量
    fixed = {}
    for t in stats:
        p = protect(t)
        if p:
            fixed[t] = p

    # 2) 基线 + 贪心升级
    cur = {}
    used = 0
    for t, ch in chains.items():
        if t in fixed:
            continue
        cur[t] = 0
        used += ch[0][0]
    # 保护项的字节：用 BPP 估（张量不在链里时无实测）
    for t, ty in fixed.items():
        if t in stats and ty in stats[t]:
            used += stats[t][ty][0]
        else:
            n = next(iter(stats[t].values()))[2] if t in stats else 0
            if n:
                used += n * BPP.get(ty, 8.5) / 8.0
    print(f"[base] 基线占用 {used/1e9:.3f} GB")
    if used > a.budget:
        print(f"[WARN] 基线已超预算 {used/1e9:.3f} > {a.budget/1e9:.3f}")

    import heapq
    heap = []
    for t, ch in chains.items():
        if t in fixed or len(ch) < 2:
            continue
        db = ch[1][0] - ch[0][0]
        de = ch[0][1] - ch[1][1]
        if db > 0 and de > 0:
            heapq.heappush(heap, (-de / db, t))

    while heap:
        dens, t = heapq.heappop(heap)
        ch = chains[t]
        i = cur.get(t, 0)
        if i + 1 >= len(ch):
            continue
        db = ch[i + 1][0] - ch[i][0]
        de = ch[i][1] - ch[i + 1][1]
        if db <= 0 or de <= 0:
            continue
        if used + db > a.budget:
            continue
        cur[t] = i + 1
        used += db
        if i + 2 < len(ch):
            db2 = ch[i + 2][0] - ch[i + 1][0]
            de2 = ch[i + 1][1] - ch[i + 2][1]
            if db2 > 0 and de2 > 0:
                heapq.heappush(heap, (-de2 / db2, t))

    # 3) 汇总
    assign = {}
    tot_err = 0.0
    for t, ch in chains.items():
        if t in fixed:
            continue
        b, e, ty = ch[cur.get(t, 0)]
        assign[t] = ty
        tot_err += e
    for t, ty in fixed.items():
        assign[t] = ty
    print(f"[out] 占用 {used/1e9:.3f} GB / 预算 {a.budget/1e9:.3f}，预测总加权误差 {tot_err:.6e}")

    # 对照：跑给出的已有 types 表
    cmp_err = None
    if a.compare:
        old = {}
        for line in open(a.compare, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("--tensor-type "):
                line = line[len("--tensor-type "):]
            k, v = line.rsplit("=", 1)
            k = k.strip()
            if k.startswith("^") and k.endswith("$"):
                k = k[1:-1].replace("\\.", ".")
            old[k] = v.strip()
        cmp_err = 0.0
        miss = 0
        for t, ch in chains.items():
            ty = old.get(t)
            per = stats.get(t, {})
            if ty in per:
                cmp_err += per[ty][1] * per[ty][2]
            else:
                miss += 1
        print(f"[compare] 旧表预测总误差 {cmp_err:.6e}（缺实测 {miss} 张量未计）")
        if cmp_err and tot_err:
            print(f"[compare] 新法误差 = 旧表 × {tot_err/cmp_err:.4f}")

    # 4) 写 plan
    lines = []
    for t, ty in sorted(assign.items()):
        esc = re.escape(t)
        lines.append(f"^{esc}$={ty}")
    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print(f"[write] {len(lines)} 条 → {a.out}")

    if a.report:
        from collections import Counter
        cnt = Counter(assign.values())
        with open(a.report, "w", encoding="utf-8") as f:
            f.write("# 实测误差分配报告（err_alloc）\n\n")
            f.write(f"- 预算: {a.budget/1e9:.3f} GB   实占: {used/1e9:.3f} GB\n")
            f.write(f"- 预测总加权误差: {tot_err:.6e}\n")
            if cmp_err:
                f.write(f"- 对照旧表误差: {cmp_err:.6e} → 比值 {tot_err/cmp_err:.4f}\n")
            f.write("\n## 类型分布\n\n")
            for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
                f.write(f"- {k}: {v} 张量 ({BPP.get(k,0):.2f} bpp)\n")
        print(f"[write] 报告 → {a.report}")


if __name__ == "__main__":
    main()
