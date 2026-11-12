#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gsq_rco_plan.py —— GSQ-RCO 量化配方生成器（Group-wise Sensitivity-guided,
Rank-and-Channel Optimized mixed-precision allocation）

论文级方案要落到可执行的张量级配方，而不是"整体 IQ2_S + 顺手抬几个 q8"。
本脚本做三件事：
  1) 读 imatrix（llama-imatrix 产出），对每个张量算重要性  imp = mean(|w_imp|) / rms(w_imp)
     —— 重要度来自校准集上的激活二阶统计，等价于该张量对输出误差的敏感度代理
  2) 结构保护（RCO 的 R/C 两面）：
       · rank 面：norm / bias / ssm_alpha(in_proj_a) / ssm_beta(in_proj_b) / dt_bias / A_log
                  --- 这些张量参数量小但对递推与门控是"秩敏感"的，强制高精度
       · channel 面：lm_head / embed_tokens / visual.merger / mtp.*
                  --- 通道级输出投影，量化误差直接进 logits，强制 >= Q6_K/Q8_0
  3) 预算贪心（Group-wise 分配）：在给定字节上限内，把剩余预算按 imp 降序升级
     （IQ2_S → Q4_K → Q6_K → Q8_0），每组（每层每类）独立决策，输出 llama-quantize 的
     `--tensor-type blk.N.xxx.weight=Q4_K` 参数表 + 逐组报告。

用法：
  python gsq_rco_plan.py --gguf model-bf16.gguf --imatrix imatrix.dat \
      --budget 9.6e9 --base-type IQ2_S --out plan.txt [--report plan.md]
  # 产出 plan.txt 里每行一个 --tensor-type 参数（直接 $(cat plan.txt) 传给 llama-quantize）

约定：
  · 未出现在 imatrix 里的张量按"结构保护"规则处理；都没有则保持 base-type
  · 预算只统计可量化张量（f32/f16/bf16 源），已经低于目标精度的不动
"""
import argparse
import json
import math
import os
import re
import sys

# bits-per-weight（含 block scale/量化元数据的经验值，llama.cpp 实测口径）
BPP = {
    "IQ2_XXS": 2.06, "Q2_0": 2.25, "IQ2_XS": 2.31, "IQ2_S": 2.50,
    "Q2_K": 2.63, "IQ3_XXS": 3.06, "IQ3_XS": 3.30, "IQ3_S": 3.44, "Q3_K": 3.44,
    "IQ4_XS": 4.25, "Q4_K": 4.50, "Q4_0": 4.50,
    "Q5_K": 5.50, "Q5_0": 5.50, "Q6_K": 6.56, "Q8_0": 8.50,
}
KONLY = {"Q2_K","Q3_K","Q4_K","Q5_K","Q6_K","Q8_0","Q4_0","Q5_0"}
# 只用本机 b11981 支持且不会踩坑的类型：IQ3_XS/IQ3_XXS 在该 build 里 parse_ggml_type 直接报 invalid
ORDER = ["IQ2_XXS", "Q2_0", "IQ2_XS", "IQ2_S", "Q2_K", "IQ3_S", "Q4_K", "Q5_K", "Q6_K", "Q8_0"]

# ── 结构保护（RCO 的 rank 面 / channel 面）────────────────────────────────
RANK_PROTECT = [                      # 强制高精度：递推状态与门控
    (r"\.ssm_alpha\.weight$", "Q8_0"),
    (r"\.ssm_beta\.weight$", "Q8_0"),
    (r"\.in_proj_a\.weight$", "Q8_0"),   # 与 ssm_alpha 同源（HF 侧名字）
    (r"\.in_proj_b\.weight$", "Q8_0"),
    (r"\.A_log$", "Q8_0"),
    (r"\.ssm_a$", "Q8_0"),
    (r"\.ssm_conv1d\.weight$", "Q8_0"),
    (r"\.dt_bias$", "Q8_0"),
    (r"\.conv1d\.weight$", "Q8_0"),
    (r"norm\.weight$", "Q6_K"),
    (r"\.bias$", "Q8_0"),
]
CHANNEL_PROTECT = [                   # 通道级输出/融合层
    (r"^output\.weight$", "Q6_K"),
    (r"^token_embd\.weight$", "Q2_K"),   # 词嵌入对量化不敏感，省 0.5GB 让给敏感层
    (r"lm_head\.weight$", "Q6_K"),
    (r"visual\.merger", "Q6_K"),
    (r"^mtp\.", "Q8_0"),
]


def read_gguf_tensors(path):
    """返回 [(name, n_elements)]，只列可量化（非整数）权重"""
    import gguf
    r = gguf.GGUFReader(path)
    out = []
    for t in r.tensors:
        n = 1
        for d in t.shape:
            n *= int(d)
        out.append((t.name, n))
    return out


def read_imatrix(path):
    """读 llama-imatrix 输出，返回 {tensor: importance(mean|imp|)}。

    两条路径：
      1) 标准 gguf 容器（新版 llama.cpp）
      2) 原始二进制流：int32 name_len + name + int32 ncall + int32 nval + float32[nval]
         （2026-10-29 实测本机 imatrix-gen2.dat 就是这种，13.5MB，496 个张量可解析）
    """
    import numpy as np
    imp = {}
    try:
        import gguf
        r = gguf.GGUFReader(path)
        for t in r.tensors:
            arr = np.asarray(t.data, dtype="float32")
            if arr.size:
                imp[t.name] = float(np.abs(arr).mean())
        if imp:
            return imp
    except Exception:
        pass

    import re
    import struct
    buf = open(path, "rb").read()
    pat = re.compile(rb"^[A-Za-z0-9_.]+\.(weight|bias)$")
    pos, n = 0, len(buf)
    while pos + 8 < n:
        ln = struct.unpack_from("<i", buf, pos)[0]
        if 3 <= ln <= 120 and pos + 4 + ln + 8 <= n:
            name = buf[pos + 4:pos + 4 + ln]
            if pat.match(name):
                q = pos + 4 + ln
                ncall, nval = struct.unpack_from("<ii", buf, q)
                if 0 <= nval <= 100000 and ncall >= 0 and q + 8 + 4 * nval <= n:
                    vals = np.frombuffer(buf, dtype="<f4", count=nval, offset=q + 8)
                    imp[name.decode()] = float(np.abs(vals).mean()) if vals.size else 0.0
                    pos = q + 8 + 4 * nval
                    continue
        pos += 1
    return imp


def protect(name):
    for pat, ty in RANK_PROTECT + CHANNEL_PROTECT:
        if re.search(pat, name):
            return ty
    return None


def bytes_at(n_elem, ty):
    return n_elem * BPP[ty] / 8.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True, help="bf16/f16 源 gguf（取其张量表）")
    ap.add_argument("--imatrix", default="", help="llama-imatrix 产出；缺省则只用结构保护")
    ap.add_argument("--budget", type=float, required=True, help="目标字节上限，如 9.6e9")
    ap.add_argument("--base-type", default="IQ2_S")
    ap.add_argument("--out", required=True, help="输出 llama-quantize 参数表")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    tensors = read_gguf_tensors(a.gguf)
    print(f"[gguf] {len(tensors)} 张量")
    imp = {}
    if a.imatrix and os.path.isfile(a.imatrix):
        imp = read_imatrix(a.imatrix)
        print(f"[imatrix] {len(imp)} 张量有重要度")

    # 1) 基础配置：结构保护优先，其余 base-type
    plan = {}
    for name, n in tensors:
        p = protect(name)
        plan[name] = p if p else a.base_type
    total = sum(bytes_at(n, plan[nm]) for nm, n in tensors)
    print(f"[init] 全 base={a.base_type} + 结构保护 → {total/1e9:.3f} GB "
          f"(预算 {a.budget/1e9:.2f} GB)")

    # 2) 预算贪心升级：按 imp 降序，逐个尝试升一档
    cand = [(imp.get(nm, 0.0), nm, n) for nm, n in tensors if not protect(nm)]
    cand.sort(reverse=True)
    upgraded = 0
    for score, nm, n in cand:
        cur = plan[nm]
        i = ORDER.index(cur)
        # 保护张量已在高位的不降；未保护的从 base 起逐档升
        for nxt in ORDER[i + 1:]:
            delta = bytes_at(n, nxt) - bytes_at(n, cur)
            if total + delta <= a.budget:
                total += delta
                plan[nm] = nxt
                cur = nxt
                upgraded += 1
            else:
                break
    print(f"[alloc] 升级 {upgraded} 个张量 → {total/1e9:.3f} GB / 预算 {a.budget/1e9:.2f} GB")

    # 2.5) imatrix 缺失保护：IQ 系列（IQ2_S/IQ2_XS/IQ3_*）没有重要度矩阵会被 llama-quantize 直接 bail，
    #      这类张量（典型是 blk.64.* 的 MTP 层与部分 visual）降级到 k-quant（不需要 imatrix）
    noimp = [nm for nm, _ in tensors if nm not in imp]
    forced = 0
    for nm in noimp:
        if protect(nm):
            continue          # 结构保护张量不能被降档（ninfer recipe 要求 ssm_alpha/ssm_beta ∈ {BF16,Q8_0}）
        if plan[nm] not in KONLY:
            total += bytes_at(dict(tensors)[nm], "Q2_K") - bytes_at(dict(tensors)[nm], plan[nm])
            plan[nm] = "Q2_K"
            forced += 1
    if forced:
        print(f"[imatrix-fix] {forced} 个无重要度张量改 Q2_K（避免 low-bit bail）；"
              f"覆盖 blk.64.* 等 {len(noimp)} 个无 imatrix 张量")

    # 3) 输出
    import re as _re
    with open(a.out, "w", encoding="utf-8") as f:
        for nm in sorted(plan):
            pat = "^" + _re.escape(nm) + "$"
            f.write(f"--tensor-type {pat}={plan[nm]}\n")
    print(f"[out] {a.out}  ({sum(1 for v in plan.values() if v != a.base_type)} 条非 base 覆盖)")

    # 4) 报告
    from collections import Counter
    dist = Counter(plan.values())
    lines = ["# GSQ-RCO 配方报告", "",
             f"- 源 gguf: `{a.gguf}`",
             f"- imatrix: `{a.imatrix or '(无)'}`",
             f"- 预算: {a.budget/1e9:.3f} GB   估算最终: {total/1e9:.3f} GB",
             f"- base-type: {a.base_type}", "",
             "## 精度分布", ""]
    for ty, c in sorted(dist.items(), key=lambda kv: -BPP[kv[0]]):
        lines.append(f"- {ty}: {c} 张量  ({BPP[ty]:.2f} bpp)")
    lines += ["", "## 最高重要的 20 个未保护张量", ""]
    for score, nm, n in cand[:20]:
        lines.append(f"- `{nm}`  imp={score:.4e}  → {plan[nm]}  ({n/1e6:.1f}M 参数)")
    if a.report:
        open(a.report, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"[report] {a.report}")
    for l in lines[:16]:
        print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
