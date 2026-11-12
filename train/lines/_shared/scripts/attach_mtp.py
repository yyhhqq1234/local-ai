#!/usr/bin/env python
"""
attach_mtp.py — 给 OxCoder-9B 装官方 Qwen3.5-9B 的 MTP 头（投机解码用）

依据（实测）
  · OxCoder-9B 与官方 Qwen3.5-9B **完全同构**：
      layers 32 / hidden 4096 / vocab 248320 / heads 16 / kv 4 / head_dim 256
      config 均声明 text_config.mtp_num_hidden_layers = 1
  · 官方 9B 权重里有 **15 个 mtp.* 张量**（mtp.fc / mtp.layers.0.{self_attn,mlp}.* / mtp.norm / pre_fc_norm_*）
  · OxCoder-9B 的 760 张量里 mtp = 0（蒸馏时被剥掉）
  ⇒ 维度完全对齐，MTP 头可直接搬运；不需要重训（先验，接受率实测后再决定是否补训）

产物
  train/lines/9b-oxcoder/models/OxCoder-9B-mtp/
      config.json …（沿用 OxCoder-9B 的元数据）
      model.safetensors        775 张量 = 760 主体 + 15 MTP
  → 可直接喂 ninfer converter；引擎侧 --spec mtp --draft-tokens 3

用法
  python train/lines/_shared/scripts/attach_mtp.py                 # 下载+拼装（约 13.5 GB 下载）
  python train/lines/_shared/scripts/attach_mtp.py --verify-only   # 只校验已有产物
"""
from __future__ import annotations
import argparse, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "train" / "models" / "OxCoder-9B"
OUT = ROOT / "train" / "models" / "OxCoder-9B-mtp"
OFFICIAL = "Qwen/Qwen3.5-9B"
SHARDS = [
    "model.safetensors-00002-of-00004.safetensors",
    "model.safetensors-00003-of-00004.safetensors",
    "model.safetensors-00004-of-00004.safetensors",
]
META_FILES = ["config.json", "generation_config.json", "tokenizer.json",
              "tokenizer_config.json", "preprocessor_config.json", "processor_config.json",
              "chat_template.jinja"]


def verify(out_dir):
    from safetensors import safe_open
    p = Path(out_dir) / "model.safetensors"
    if not p.exists():
        return {"ok": False, "err": f"不存在: {p}"}
    with safe_open(str(p), framework="pt") as f:
        keys = list(f.keys())
    mtp = [k for k in keys if k.startswith("mtp.")]
    return {
        "ok": len(mtp) == 15,
        "file": str(p),
        "total_tensors": len(keys),
        "mtp_tensors": len(mtp),
        "mtp_sample": mtp[:6],
        "size_gib": round(p.stat().st_size / 2**30, 2),
    }


MTP_LOCAL = ROOT / "train" / "models" / "mtp" / "qwen3.5-9b-mtp.safetensors"


def extract(mtp_out: Path) -> dict:
    """只抽取官方 9B 的 15 个 mtp.* 张量，存成本地独立文件（训练后拼装免下载）"""
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open
    from safetensors.torch import save_file

    cache = {}
    for shard in SHARDS:
        try:
            p = hf_hub_download(OFFICIAL, shard)
        except Exception as e:
            print(f"[WARN] {shard} 失败: {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
            continue
        with safe_open(p, framework="pt", device="cpu") as f:
            for k in f.keys():
                if k.startswith("mtp."):
                    cache[k] = f.get_tensor(k)
        print(f"[ok] {shard}: 累计 {len(cache)}", file=sys.stderr)
        if len(cache) >= 15:
            break
    if not cache:
        raise SystemExit("[FATAL] 未取到任何 mtp 张量")

    mtp_out.parent.mkdir(parents=True, exist_ok=True)
    save_file(cache, str(mtp_out), metadata={"source": OFFICIAL, "kind": "mtp"})
    info = {
        "file": str(mtp_out),
        "source": OFFICIAL,
        "mtp_tensors": len(cache),
        "ok": len(cache) == 15,
        "mib": round(mtp_out.stat().st_size / 2**20, 1),
        "keys": sorted(cache),
        "shapes": {k: list(v.shape) for k, v in sorted(cache.items())},
        "dtypes": {k: str(v.dtype) for k, v in sorted(cache.items())},
    }
    (mtp_out.with_suffix(".json")).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract-only", action="store_true", help="只抽取 MTP 存本地，不拼装")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--src", default=str(SRC), help="目标权重目录（训练后指向 merged 权重）")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--mtp-file", default=str(MTP_LOCAL), help="本地 MTP 权重文件（存在则优先，免下载）")
    a = ap.parse_args()

    if a.extract_only:
        print(json.dumps(extract(Path(a.mtp_file)), ensure_ascii=False, indent=2))
        return

    if a.verify_only:
        print(json.dumps(verify(a.out), ensure_ascii=False, indent=2))
        return

    src = Path(a.src)
    if not (src / "model.safetensors").exists():
        sys.exit(f"[FATAL] 源权重不存在: {src / 'model.safetensors'}")

    from huggingface_hub import hf_hub_download
    from safetensors import safe_open
    from safetensors.torch import save_file
    import torch

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # 1) 元数据沿用源权重（用 --src 参数，不是模块级常量 SRC）
    for f in META_FILES:
        s = src / f
        if s.exists():
            shutil.copy2(s, out / f)

    # 2) MTP 张量：本地文件优先（不存在则现场抽取并落盘）
    from safetensors import safe_open
    mtp_path = Path(a.mtp_file)
    if not mtp_path.exists():
        print(f"[info] 本地无 MTP，现抽取 → {mtp_path}", file=sys.stderr)
        extract(mtp_path)
    with safe_open(str(mtp_path), framework="pt", device="cpu") as f:
        mtp_tensors = {k: f.get_tensor(k) for k in f.keys() if k.startswith("mtp.")}
    print(f"[ok] MTP 取自本地: {len(mtp_tensors)} 张量 ← {mtp_path}", file=sys.stderr)

    if len(mtp_tensors) != 15:
        print(f"[FATAL] MTP 张量不完整: {len(mtp_tensors)}/15", file=sys.stderr)
        sys.exit(2)

    # 3) 合并：源权重主体 + MTP（用 --src 参数）
    merged = {}
    with safe_open(str(src / "model.safetensors"), framework="pt", device="cpu") as f:
        for k in f.keys():
            merged[k] = f.get_tensor(k)
    n_body = len(merged)
    merged.update(mtp_tensors)

    # 4) 校验形状与 dtype
    bad = []
    for k, v in mtp_tensors.items():
        if v.dtype not in (torch.bfloat16, torch.float32):
            bad.append(f"{k}: dtype={v.dtype}")
    if bad:
        print(f"[WARN] MTP dtype 异常: {bad[:3]}", file=sys.stderr)

    save_file(merged, str(out / "model.safetensors"), metadata={"format": "pt"})
    summary = {
        "out": str(out),
        "body_tensors": n_body,
        "mtp_tensors": len(mtp_tensors),
        "total": len(merged),
        "size_gib": round((out / "model.safetensors").stat().st_size / 2**30, 2),
        "mtp_keys": sorted(mtp_tensors),
    }
    (out / "MTP-ATTACH.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
