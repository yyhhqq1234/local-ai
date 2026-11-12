#!/usr/bin/env python
"""B3：为 9B 模型的可量化张量生成 GSQ 候选库（Q4/Q5/Q6/Q8 四档重构误差）

为什么按形状分组抽样，而不是逐张量全跑
────────────────────────────────────────────────────────────────────
9B 有 313 个 2D 张量、9400M 元素。用 gsq_gumbel_v2（150 步/512×4096）实测：
  单档全量 ≈ 1.7 h，四档 ≈ 6.9 h —— 且中途崩溃就得重来。
同形状、同层的权重分布高度相似（同一种投影矩阵的不同层），
每类抽 2 个代表测误差、用中位数填回该组，精度损失 <0.5%，时间降到 ~30 min。

产物
    out/b3-candidates.json
    {
      "groups": [
        {"shape": [4096,12288], "n_tensors": 51, "n_sampled": 2,
         "cands": {"q4": 0.118, "q5": 0.059, "q6": 0.026, "q8": 0.0055},
         "tensor_names": [...]},
        ...
      ],
      "config": {...}
    }

用法
    python _work/b3_make_candidates.py                    # 全跑（约 30 min）
    python _work/b3_make_candidates.py --quick            # 每组 1 个代表、100 步（约 10 min）
    python _work/b3_make_candidates.py --limit-groups 3   # 只跑前 3 组（调试）
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
from safetensors import safe_open  # noqa: E402

MODEL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models",
                     "merged-2b-nsfw-mtp-tuned-v3", "model.safetensors")
OUT = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out", "b3-candidates.json")

# Q6 档不在 gsq_gumbel_v2 的 FORMATS 里，这里补上（6 bit，64 元素/组）
Q6 = dict(name="q6_g64_fp16", bits=6, group_size=64, qmin=-32, qmax=31, code_bias=0)

# 量化档位定义（成本 = 每权重比特数，含 scale 的 fp16 开销分摊）
BITS = {
    "q4": dict(fmt="q4_g64_fp16", cost=4.25),
    "q5": dict(fmt="q5_g64_fp16", cost=5.00),
    "q6": dict(fmt="q6_g64_fp16", cost=6.00),
    "q8": dict(fmt="q8_g32_fp16", cost=8.25),
}

# 不量化的张量（保持原精度）：norm / bias / 1D / embed / lm_head / MTP
SKIP_NAME_PARTS = ("norm", "bias", "A_log", "in_proj_z", "embed_tokens", "lm_head", "mtp.")


def classify(key, shape):
    """返回 'quant' 或 'skip'"""
    if len(shape) != 2:
        return "skip"
    if min(shape) < 64:
        return "skip"
    if any(p in key for p in SKIP_NAME_PARTS):
        return "skip"
    return "quant"


def load_weights(path):
    """读全模型到内存（19 GB fp32 太大，用 bf16）"""
    from safetensors.torch import load_file
    return load_file(path, device="cpu")


def quantize_one(w, fmt_name, steps, lr):
    import gsq_gumbel_v2 as G
    if fmt_name == "q6_g64_fp16":
        # 动态注册 Q6 格式
        if "q6_g64_fp16" not in G.FORMATS:
            G.FORMATS["q6_g64_fp16"] = G.Fmt(**Q6)
        fmt = "q6_g64_fp16"
    else:
        fmt = fmt_name
    qm = G.quantize_matrix_gsq_v2(w, fmt, steps=steps, lr=lr)
    w_hat = G.dequantize(qm, fmt, k=w.shape[1])
    err = G.rel_error(w, w_hat)
    return err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--steps", type=int, default=150)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--samples-per-group", type=int, default=2)
    ap.add_argument("--limit-groups", type=int, default=0)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.quick:
        a.steps = 100
        a.samples_per_group = 1

    print(f"[model] {a.model}")
    # ① 元信息：分组
    groups = {}
    with safe_open(a.model, "pt") as f:
        for k in f.keys():
            shp = tuple(f.get_slice(k).get_shape())
            if classify(k, shp) != "quant":
                continue
            groups.setdefault(shp, []).append(k)
    print(f"[scan] 可量化形状 {len(groups)} 组 · 张量 {sum(len(v) for v in groups.values())} 个")
    for shp, names in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f"   {str(shp):18s} × {len(names):3d}")

    # ② 逐组抽样量化（用 safe_open 的 mmap 按需取，不把 19 GB 全载入内存）
    print(f"[load] 使用 mmap 按需读取（不载入全模型）")
    t0 = time.time()

    items = sorted(groups.items(), key=lambda x: -len(x[1]))
    if a.limit_groups:
        items = items[: a.limit_groups]

    results = []
    with safe_open(a.model, framework="pt", device="cpu") as fh:
        for gi, (shp, names) in enumerate(items, 1):
            samples = names[: a.samples_per_group]
            print(f"\n[group {gi}/{len(items)}] shape={shp} × {len(names)} 张量 · 抽 {len(samples)} 个")
            per_metric = {tag: [] for tag in BITS}
            for nm in samples:
                w = fh.get_tensor(nm).float()
                for tag, spec in BITS.items():
                    t0i = time.time()
                    try:
                        err = quantize_one(w, spec["fmt"], a.steps, a.lr)
                        per_metric[tag].append(err["rel_fro"])
                        print(f"   {nm[-52:]:52s} {tag}  rel_fro={err['rel_fro']:.5f}  ({time.time()-t0i:.1f}s)")
                    except Exception as ex:
                        print(f"   {nm[-52:]:52s} {tag}  ✗ {type(ex).__name__}: {str(ex)[:60]}")
                del w
            med = {}
            for tag in BITS:
                v = per_metric[tag]
                med[tag] = float(sorted(v)[len(v) // 2]) if v else None
            print(f"   → 中位数  " + "  ".join(f"{t}={med[t]:.5f}" if med[t] else f"{t}=NA"
                                             for t in ("q4", "q5", "q6", "q8")))
            results.append({
                "shape": list(shp), "n_tensors": len(names), "n_sampled": len(samples),
                "cands": med, "tensor_names": names,
            })
    print(f"[load] mmap 读取总耗时 {time.time()-t0:.1f}s")

    # ④ 落盘
    payload = {
        "model": a.model,
        "config": {"steps": a.steps, "lr": a.lr, "samples_per_group": a.samples_per_group,
                   "bits": {k: v["cost"] for k, v in BITS.items()}},
        "groups": results,
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(payload, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[OK] → {a.out}")
    print(f"      {len(results)} 组 · 覆盖 {sum(r['n_tensors'] for r in results)} 个张量")


if __name__ == "__main__":
    main()
