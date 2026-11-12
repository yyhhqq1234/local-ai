#!/usr/bin/env bash
# mix-v8 训练：kitty 清理版 + 2A lite（禁工具负例 + 评测形态）
#
# 与 mix-v5 的四处差异（对应 mix-v5 的三条命门）：
#   数据      mix-v5.jsonl            → mix-v8.jsonl（kitty 44 行污染已清；2A 换成 lite 850 行）
#   2A 形态   抽象 issue（2.9% 有文件）→ 评测形态（T1 文件+函数 / T2 文件）+ system 禁工具
#   配比      行份额 7.78%（梯度 31%） → 梯度份额 9.96%
#   长样本    >1200 字符 7.8%          → 0.31%
#
# 参数仍逐项抄 r3（ctx2048 / r32 / alpha64 / lr3e-5 / ga4 / cosine / adamw_torch / bf16 /
# completion_only_loss / seed42 / dropout0.1 / wd0.01），只换 data / out / save-steps。
set -u
cd "$(dirname "$0")/../.." || exit 1

DATA=${DATA:-train/lines/9b-oxcoder/data/_legacy/mix-v8.jsonl}
OUTDIR=${OUTDIR:-train/lines/9b-oxcoder/out/mix-v8}
INIT=${INIT:-train/lines/9b-oxcoder/out/re-stage1-r3/final}
PY=./train/.venv/Scripts/python.exe

[ -f "$PY" ] || { echo "[FATAL] venv 缺失"; exit 1; }
[ -f "$DATA" ] || { echo "[FATAL] 数据缺失: $DATA"; exit 1; }
[ -d "$INIT" ] || { echo "[FATAL] init-adapter 缺失: $INIT"; exit 1; }

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

if [ "${1:-}" = dry ]; then
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}" --dry-run
  exit $?
fi

echo "[START] $(date '+%F %T')  mix-v8 → $OUTDIR"
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py "${ARGS[@]}"
RC=$?
echo "[EXIT] rc=$RC  $(date '+%F %T')"
exit $RC
