#!/usr/bin/env bash
# mix-v5 训练：方案 Y（rehearsal）—— kitty 全量 23718 + 2A 全量 2001，一次训完
#
# 为什么是这套参数（TASKPOINT §A6 + 根因 C8）：
#   · 基线是 r3（RE 75.0%），不是 2A。参数逐项抄 r3 的 training_args.bin：
#     ctx2048 / r32 / alpha64 / lr3e-5 / ga4 / bs1 / cosine / adamw_torch / bf16
#     / completion_only_loss / seed42 / lora_dropout 0.1 / weight_decay 0.01
#   · 唯一差异：--data mix-v5.jsonl、--out mix-v5、--init-adapter r3/final、
#     --save-steps 400（减少落盘热循环）、--epochs 1（25719/4=6430 步，rehearsal 一轮足够）
#   · r3 的 final 不覆盖（输出到新目录），失败可回退 r3
#
# 用法：
#   bash train/lines/_shared/scripts/run_mix_v5.sh dry     # 只回显配置
#   bash train/lines/_shared/scripts/run_mix_v5.sh         # 正式跑
set -u
cd "$(dirname "$0")/../.." || exit 1

PY=./train/.venv/Scripts/python.exe
[ -f "$PY" ] || { echo "[FATAL] 训练虚拟环境缺失: $PY"; exit 1; }
[ -f train/lines/9b-oxcoder/data/_legacy/mix-v5.jsonl ] || { echo "[FATAL] 混合集缺失: train/lines/9b-oxcoder/data/_legacy/mix-v5.jsonl（先跑 mix_kitty_2a.py）"; exit 1; }
[ -d train/lines/9b-oxcoder/out/re-stage1-r3/final ] || { echo "[FATAL] init-adapter 缺失: train/lines/9b-oxcoder/out/re-stage1-r3/final"; exit 1; }

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80
export VRAM_FRAC=0.93
export PYTHONIOENCODING=utf-8
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_SYMLINKS=1
export OMP_NUM_THREADS=6
export MKL_NUM_THREADS=6

ARGS=(
  --base train/lines/9b-oxcoder/models/OxCoder-9B
  --data train/lines/9b-oxcoder/data/_legacy/mix-v5.jsonl
  --stage re
  --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final
  --out train/lines/9b-oxcoder/out/mix-v5
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

if [ "${1:-}" = "dry" ]; then
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}" --dry-run
  exit $?
fi

echo "[START] $(date '+%F %T')  mix-v5 rehearsal 1 epoch → train/lines/9b-oxcoder/out/mix-v5"
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}"
RC=$?
echo "[EXIT] rc=$RC  $(date '+%F %T')"
exit $RC
