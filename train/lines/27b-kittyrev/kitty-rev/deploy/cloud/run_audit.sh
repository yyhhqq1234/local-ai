#!/bin/bash
# run_audit.sh —— 后台跑 gguf 全量审计（51G 逐张量读，约 5-10 分钟）
set -u
R=/root/autodl-tmp/kitty-rev
cd "$R"
echo "[audit] start $(date '+%F %T')"
PYTHONPATH=/root/autodl-tmp/lc/gguf-py /root/miniconda3/bin/python cloud/gguf_audit.py gguf/gen2-bf16.gguf
echo "[audit] rc=$? end $(date '+%F %T')"
