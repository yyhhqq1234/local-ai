#!/usr/bin/env bash
# 方案 Z · A 腿：2A 专用 adapter（从基座直接训，不掺 kitty）
#   → 天然不会吐工具调用（training 数据里一条 tool_call 都没有）
#   → 推理时只承接纯编程问答
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
DATA=${DATA:-train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl}
OUTDIR=${OUTDIR:-train/lines/9b-oxcoder/out/z-2a}

[ -f "$DATA" ] || { echo "[FATAL] 缺 $DATA"; exit 1; }

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VRAM_FRAC=0.93
export PYTHONIOENCODING=utf-8
export HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=6
export MKL_NUM_THREADS=6

ARGS=(
  --base train/lines/9b-oxcoder/models/OxCoder-9B
  --data "$DATA"
  --stage re
  --out "$OUTDIR"
  --ctx 2048
  --epochs 1
  --lr 3e-5
  --ga 4
  --bs 1
  --optim adamw_torch
  --use-liger-ce
  --lora-dropout 0.1
  --weight-decay 0.01
  --save-steps 100
  --save-total-limit 6
)

if [ "${1:-}" = dry ]; then "$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}" --dry-run; exit $?; fi
echo "[START] $(date '+%F %T')  Z-2A（基座 → 2A，无 kitty）→ $OUTDIR"
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}"
RC=$?
echo "[EXIT] rc=$RC $(date '+%F %T')"
