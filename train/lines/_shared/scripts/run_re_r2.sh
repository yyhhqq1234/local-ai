#!/usr/bin/env bash
# RE 补训 2 epoch：从 re-stage1-fixed/final 的 LoRA 权重继续，全新 optimizer + cosine
# 用法： bash train/lines/_shared/scripts/run_re_r2.sh          # 正式跑
#        bash train/lines/_shared/scripts/run_re_r2.sh dry      # 只回显配置
set -u
cd "$(dirname "$0")/../.." || exit 1

PY=./train/.venv/Scripts/python.exe
[ -f "$PY" ] || { echo "[FATAL] 训练虚拟环境缺失: $PY"; exit 1; }

export PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80
export VRAM_FRAC=0.93
export PYTHONIOENCODING=utf-8
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_SYMLINKS=1
export OMP_NUM_THREADS=6
export MKL_NUM_THREADS=6

ARGS=(
  --base train/lines/9b-oxcoder/models/OxCoder-9B
  --data train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl
  --stage re
  --init-adapter train/lines/9b-oxcoder/out/re-stage1-fixed/final
  --out train/lines/9b-oxcoder/out/re-stage1-r2
  --ctx 2048
  --epochs 2
  --lr 5e-5
  --ga 4
  --bs 1
  --optim adamw_torch
  --use-liger-ce
  --save-steps 200
  --save-total-limit 8
)

if [ "${1:-}" = "dry" ]; then
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}" --dry-run
  exit $?
fi

echo "[START] $(date '+%F %T')  RE 补训 2 epoch → train/lines/9b-oxcoder/out/re-stage1-r2"
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}"
RC=$?
echo "[EXIT] rc=$RC  $(date '+%F %T')"
exit $RC
