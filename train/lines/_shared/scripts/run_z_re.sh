#!/usr/bin/env bash
# 方案 Z · B 腿：RE adapter（在 r3 之上补「调用范式」）
#   data = kitty-clean 23674 + 范式增广 600（梯度份额 2.08%）
#   目的：把 47 个缺 <tool_call> 范例的工具补上，消掉 kitty_load / kitty_interceptor 这类自造名
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
DATA=${DATA:-train/lines/9b-oxcoder/data/_legacy/mix-z-re.jsonl}
OUTDIR=${OUTDIR:-train/lines/9b-oxcoder/out/z-re}
INIT=${INIT:-train/lines/9b-oxcoder/out/re-stage1-r3/final}

[ -f "$DATA" ] || { echo "[FATAL] 缺 $DATA"; exit 1; }
[ -d "$INIT" ] || { echo "[FATAL] 缺 $INIT"; exit 1; }

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
  --init-adapter "$INIT"
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
  --save-steps 400
  --save-total-limit 8
)

if [ "${1:-}" = dry ]; then "$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}" --dry-run; exit $?; fi
echo "[START] $(date '+%F %T')  Z-RE（r3 + 调用范式）→ $OUTDIR"
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}"
RC=$?
echo "[EXIT] rc=$RC $(date '+%F %T')"
