#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dl_base.py —— 用 hf-mirror 下载 huihui 基座到本地目录（断点续传，hf_hub 自带）"""
import os, sys, time
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
DST = "/root/autodl-tmp/base-hf/Huihui"

from huggingface_hub import snapshot_download

t0 = time.time()
print(f"[dl] repo={REPO} dst={DST} endpoint={os.environ['HF_ENDPOINT']}", flush=True)
p = snapshot_download(
    repo_id=REPO,
    local_dir=DST,
    resume_download=True,
    max_workers=8,
    ignore_patterns=["*.pth", "*.pt", "*.bin.index.json"],
)
n = sum(len(fs) for _, _, fs in os.walk(p))
sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
print(f"[dl] done path={p} files={n} bytes={sz} ({sz/1e9:.1f} GB) elapsed={(time.time()-t0)/60:.1f} min", flush=True)
