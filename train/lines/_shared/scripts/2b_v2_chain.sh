#!/usr/bin/env bash
# 2B v2：修 GateFPR=1.0（常规请求全被拒）
#   诊断（2026-11-01 gate-local-2b.json）：
#     gate_recall 0.8667（略低于 0.90）· gate_leak 0.0 ✓ · gate_fpr 1.0 ✗ · trap_refusal 1.0 ✗
#   根因：负样本 13998 : 常规对照 1183 ≈ 12:1 → 模型学成「没开关就拒」，把常规请求也拒了
#   处方（PLAN §5.3.4）：ctl 提到 2500、neg-per-pos 从 2.0 降到 1.5，重训带 seed 42
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/2b-v2.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
log "================ 2B v2 启动 pid=$$ ================"

# 1) 备份旧门控集
if [ -d train/lines/9b-oxcoder/data/nsfw-gated ] && [ ! -d train/lines/9b-oxcoder/data/nsfw-gated-v1 ]; then
  mv train/lines/9b-oxcoder/data/nsfw-gated train/lines/9b-oxcoder/data/nsfw-gated-v1 && log "旧数据已备份 → train/lines/9b-oxcoder/data/nsfw-gated-v1"
fi

# 2) 重建：ctl 2500 · neg-per-pos 1.5
if [ ! -f train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl ]; then
  log "重建门控集：ctl=3500 · neg-per-pos=0.6 · seed=42（ratio_ctl 0.135，修正 FPR）"
  PYTHONIOENCODING=utf-8 "$PY" train/lines/_shared/scripts/build_nsfw_gated.py \
    --ctl-n 3500 --neg-per-pos 0.6 --seed 42 >> "$LOG" 2>&1
  log "build rc=$?"
fi
wc -l train/lines/9b-oxcoder/data/nsfw-gated/*.jsonl 2>/dev/null | tee -a "$LOG"

# 3) 训练（从 z-2a-v7 续训，固定 seed）
if [ ! -d "$OUT/2b-nsfw-v2/final" ]; then
  log "训练开始：init=z-2a-v7 · seed=42 · lr 2e-5 · 1 epoch"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl \
    --stage nsfw --init-adapter "$OUT/z-2a-v7/final" --out "$OUT/2b-nsfw-v2" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 300 --save-total-limit 8 >> "$L/2b-v2-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "final 已存在，跳过训练"
fi

# 4) 门控评测
if [ -d "$OUT/2b-nsfw-v2/final" ]; then
  log "门控评测（val 85）"
  PYTHONIOENCODING=utf-8 "$PY" train/lines/_shared/scripts/nsfw_gate_local.py \
    --adapter "$OUT/2b-nsfw-v2/final" --val train/lines/9b-oxcoder/data/eval/val/nsfw-gate.jsonl \
    --max-new 512 --out "$L/gate-local-2b-v2.json" >> "$LOG" 2>&1
  log "门控评测 rc=$?（0=达标）"
fi
log "================ 2B v2 结束 ================"
