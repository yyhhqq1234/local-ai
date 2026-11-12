#!/usr/bin/env bash
# RE 补训后三档对比评测：判断 2 epoch 是否过拟合
#   档1 re-stage1-fixed/final      累计数据 1 遍（首轮 1 epoch）
#   档2 re-stage1-r2/checkpoint-1400  累计 2 遍（首轮 + 本轮第 1 epoch）
#   档3 re-stage1-r2/final         累计 3 遍（首轮 + 本轮 2 epoch）
#
# 判据：
#   · 工具命中：档3 >= 档2 >= 档1 → 补训有效
#   · 编造数：kitty_dbvm 在档3 应消失
#   · 若档3 的工具命中反低于档2 → 过拟合，用档2
#
# 用法： bash train/lines/_shared/scripts/run_eval_r2.sh
set -u
cd "$(dirname "$0")/../.." || exit 1

PY=./train/.venv/Scripts/python.exe
[ -f "$PY" ] || { echo "[FATAL] venv 缺失"; exit 1; }

export PYTHONIOENCODING=utf-8
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_SYMLINKS=1

OUTDIR=train/logs
mkdir -p "$OUTDIR"
TS=$(date '+%Y%m%d-%H%M')

CAND=(
  "档1-首轮1ep:train/lines/9b-oxcoder/out/re-stage1-fixed/final"
  "档2-累计2ep:train/lines/9b-oxcoder/out/re-r2-ckpt1400-snapshot"
  "档3-累计3ep:train/lines/9b-oxcoder/out/re-stage1-r2/final"
)

echo "=========================================================="
echo " RE 三档对比评测  $TS"
echo "=========================================================="

for item in "${CAND[@]}"; do
  tag="${item%%:*}"
  path="${item#*:}"
  if [ ! -d "$path" ]; then
    echo "[SKIP] $tag → $path 不存在"
    continue
  fi
  echo ""
  echo "--- $tag  ($path) ---"
  "$PY" -u train/lines/_shared/scripts/eval_re_heldout.py \
      --adapter "$path" --n 10 --seed 7 --max-new 300 \
      2>&1 | tee "$OUTDIR/eval-r2-${tag}-${TS}.log" | tail -25
done

echo ""
echo "=========================================================="
echo " 汇总判读："
echo "   档3 工具命中 >= 档2 >= 档1  且 档3 无 kitty_dbvm → 2 epoch 成功"
echo "   档3 命中 < 档2                                → 过拟合，改用档2"
echo "   各档日志 → $OUTDIR/eval-r2-*-${TS}.log"
echo "=========================================================="
