#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""local_merge_lora.py —— 本机分片级 LoRA merge（RAM 轻，31.5GB 机器可跑 27B）

为什么不用 scripts/merge.py：
  官方 peft merge 走 AutoModelForCausalLM.from_pretrained 全量载入 → 27B bf16 需
  ~54GB RAM，本机 31.5GB 直接 OOM。本脚本按 safetensors **片**循环：
  单片刻度峰值 ≈ 3.1GB(shard) + 0.4GB(fp32 单张量 delta)，全程 < 6GB。

关键换算：
  delta_W = (lora_B @ lora_A) * (alpha / r)     r=16 alpha=32 → scale 2.0
  W_merged = W_base + delta_W  （bf16 存储，计算用 fp32）

命名解析（血泪）：
  adapter 在 merged-v61（纯文本塔）上训 → `base_model.model.model.layers.N.*`
  pristine 基座是 VL 包装            → `model.language_model.layers.N.*`
  → 两侧都做 norm()（剥 base_model.model. / language_model. / model.）后按
    `layers.N.<attn|mlp>.<proj>.weight` 对齐，避免硬编码前缀。

用法：
  # 0) 自检：不写盘，只报能对上多少 LoRA 模块（务必先跑这个）
  ./.venv/Scripts/python.exe scripts/local_merge_lora.py \\
      --base train/lines/27b-kittyrev/base/Qwen3.8-27B --adapter train/lines/27b-kittyrev/local-pack/gen2/adapter-ckpt350 --dry

  # 1) 实跑（分片写盘，可中断重跑；已完成的片会跳过）
  ./.venv/Scripts/python.exe scripts/local_merge_lora.py \\
      --base train/lines/27b-kittyrev/base/Qwen3.8-27B --adapter train/lines/27b-kittyrev/local-pack/gen2/adapter-ckpt350 \\
      --out train/lines/27b-kittyrev/merged/gen2v2

  # 2) 只算前 2 片（快速验算）
  ... --limit-shards 2 --out train/lines/27b-kittyrev/merged/_probe
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

import torch
from safetensors import safe_open
from safetensors.torch import load_file, save_file


def norm(name: str) -> str:
    n = name
    for p in ("base_model.model.", "language_model.", "model."):
        n = n.replace(p, "")
    return n


def scan_adapter(adir):
    """返回 {norm_module: (A, B)}，A/B 为 fp32 CPU tensor。"""
    p = os.path.join(adir, "adapter_model.safetensors")
    if not os.path.isfile(p):
        raise SystemExit(f"[FATAL] 缺 {p}")
    cfg = json.load(open(os.path.join(adir, "adapter_config.json"), encoding="utf-8"))
    r = int(cfg["r"])
    alpha = float(cfg["lora_alpha"])
    scale = alpha / r
    pairs = {}
    with safe_open(p, framework="pt", device="cpu") as f:
        keys = list(f.keys())
        for k in keys:
            if ".lora_A." not in k:
                continue
            mod = k.split(".lora_A.")[0]
            kb = mod + ".lora_B.weight"
            if kb not in keys:
                raise SystemExit(f"[FATAL] {mod} 只有 A 没有 B")
            pairs[norm(mod)] = (f.get_tensor(k).float(), f.get_tensor(kb).float())
    print(f"[adapter] r={r} alpha={alpha:g} scale={scale:g} modules={len(pairs)}")
    return pairs, scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit-shards", type=int, default=0)
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp16", "fp32"])
    a = ap.parse_args()

    td = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[a.dtype]
    t0 = time.time()
    deltas, scale = scan_adapter(a.adapter)

    idx_path = os.path.join(a.base, "model.safetensors.index.json")
    single = os.path.join(a.base, "model.safetensors")
    if os.path.isfile(idx_path):
        idx = json.load(open(idx_path, encoding="utf-8"))
        wmap = idx["weight_map"]
        shards = sorted(set(wmap.values()))
    elif os.path.isfile(single):
        wmap = None
        shards = ["model.safetensors"]
    else:
        raise SystemExit(f"[FATAL] {a.base} 里既无 index.json 也无 model.safetensors")

    if a.limit_shards:
        shards = shards[: a.limit_shards]
    print(f"[base] shards={len(shards)} dtype_out={a.dtype}")

    # 预检：每个 LoRA 模块能否在 base 权重名里找到
    all_names = []
    for s in (shards if a.limit_shards else sorted(set(shards))):
        with safe_open(os.path.join(a.base, s), framework="pt", device="cpu") as f:
            all_names.extend(list(f.keys()))
    base_norm = {norm(n): n for n in all_names}
    hit = [m for m in deltas if m + ".weight" in base_norm]
    miss = [m for m in deltas if m + ".weight" not in base_norm]
    print(f"[map] LoRA 模块命中 base {len(hit)}/{len(deltas)}")
    if miss:
        print(f"[map] 未命中示例: {miss[:3]}")
    if not hit:
        raise SystemExit("[FATAL] 一个都對不上，命名规则不符，停在 dry 阶段先查")
    if miss and not a.dry:
        if a.limit_shards:
            # 只算前 N 片时，其余模块的张量本来就不在这一片里 → 允许partial（探路用）
            print(f"[map] --limit-shards 探路模式：{len(miss)} 个模块不在选中片内，跳过严格校验")
        else:
            raise SystemExit(f"[FATAL] 有 {len(miss)} 个模块对不上，拒绝写半成品")

    if a.dry:
        # 只算 delta 统计，验证量级（v6 实测 rms 3e-4 量级）
        rms = []
        for m in hit[:12]:
            A, B = deltas[m]
            d = (B @ A) * scale
            rms.append(float(d.pow(2).mean().sqrt()))
        print(f"[dry] delta rms 样本({len(rms)}): "
              + " ".join(f"{v:.2e}" for v in rms))
        print("[dry] 未写盘。确认 rms 在 1e-5~1e-3 量级后再去掉 --dry 实跑")
        return 0

    os.makedirs(a.out, exist_ok=True)
    new_wmap = {}
    merged_cnt = 0
    for si, s in enumerate(shards, 1):
        dst = os.path.join(a.out, s)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            print(f"[{si}/{len(shards)}] skip 已存在 {s}")
            with safe_open(dst, framework="pt", device="cpu") as f:
                for k in f.keys():
                    new_wmap[k] = s
            continue
        src = os.path.join(a.base, s)
        sd = load_file(src, device="cpu")
        out = {}
        local_merged = 0
        for k, v in sd.items():
            m = norm(k)
            key = m[:-len(".weight")] if m.endswith(".weight") else None
            if key and key in deltas:
                A, B = deltas[key]
                d = (B @ A) * scale
                if d.shape != v.shape:
                    raise SystemExit(f"[FATAL] shape 不符 {k}: base{tuple(v.shape)} delta{tuple(d.shape)}")
                out[k] = (v.float() + d).to(td)
                local_merged += 1
                del d
            else:
                out[k] = v.to(td)
            new_wmap[k] = s
        save_file(out, dst, metadata={"format": "pt"})
        merged_cnt += local_merged
        del sd, out
        print(f"[{si}/{len(shards)}] {s} merged_tensors={local_merged} "
              f"size={os.path.getsize(dst)/2**30:.2f}GiB elapsed={(time.time()-t0)/60:.1f}min")

    if not a.limit_shards:
        # 索引 + 附属文件
        if wmap is not None:
            total = 0
            for s in shards:
                total += os.path.getsize(os.path.join(a.out, s))
            json.dump({"metadata": {"total_size": total}, "weight_map": new_wmap},
                      open(os.path.join(a.out, "model.safetensors.index.json"), "w", encoding="utf-8"),
                      indent=2)
            print(f"[out] index.json 写出，总 {total/2**30:.2f}GiB")
        for n in sorted(os.listdir(a.base)):
            if n.endswith((".safetensors", ".index.json")):
                continue
            sp, dp = os.path.join(a.base, n), os.path.join(a.out, n)
            if not os.path.isfile(sp) or os.path.exists(dp):
                continue
            shutil.copy2(sp, dp)
            print(f"[out] copy {n}")

    print(f"[DONE] merged_tensors={merged_cnt} 耗时={(time.time()-t0)/60:.1f}min → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
