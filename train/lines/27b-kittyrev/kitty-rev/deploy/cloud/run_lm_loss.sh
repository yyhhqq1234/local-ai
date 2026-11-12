#!/bin/bash
# run_lm_loss.sh —— 后台用 transformers(CPU,bf16) 直接算 merged-gen2 的 LM loss
set -u
R=/root/autodl-tmp/kitty-rev
cd "$R"
echo "[loss] start $(date '+%F %T')"
/root/miniconda3/bin/python -u cloud/hf_lm_loss.py merged-gen2 3
echo "[loss] rc=$? end $(date '+%F %T')"
