# -*- coding: utf-8 -*-
"""dl_base_27b.py —— 下载 Qwen/Qwen3.8-27B（bf16, 18 shards, ≈51.8 GiB）到 train/base/Qwen3.8-27B

不依赖 transformers：下载完直接用 json 校验 config.architectures。
用法：python dl_base_27b.py [--repo Qwen/Qwen3.8-27B] [--dest ...] [--workers 8]
"""
import argparse
import json
import os
import shutil
import sys
import time

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(TRAIN_ROOT, "hf"))


def du(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 2 ** 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Qwen/Qwen3.8-27B")
    ap.add_argument("--dest", default=os.path.join(TRAIN_ROOT, "base", "Qwen3.8-27B"))
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    from huggingface_hub import snapshot_download

    free = shutil.disk_usage(TRAIN_ROOT).free / 2 ** 30
    print(f"[disk ] free={free:.1f} GiB  dest={a.dest}", flush=True)
    os.makedirs(a.dest, exist_ok=True)
    t0 = time.time()
    path = snapshot_download(
        repo_id=a.repo,
        local_dir=a.dest,
        allow_patterns=["*.json", "*.safetensors", "*.model", "*.jinja", "*.txt"],
        max_workers=a.workers,
    )
    dt = time.time() - t0
    size = free - shutil.disk_usage(TRAIN_ROOT).free / 2 ** 30
    print(f"[done ] {path}  elapsed={dt/60:.1f} min  size={du(a.dest):.2f} GiB  used={size:.1f} GiB", flush=True)

    cfg_path = os.path.join(a.dest, "config.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    arch = cfg.get("architectures")
    print(f"[config] model_type={cfg.get('model_type')} architectures={arch}", flush=True)
    ok = bool(arch) and any("Qwen3_5" in x for x in arch)
    shards = [f for f in os.listdir(a.dest) if f.endswith(".safetensors")]
    print(f"[shards] {len(shards)} files", flush=True)
    print("[VERDICT]", "PASS" if ok and len(shards) >= 18 else "CHECK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
