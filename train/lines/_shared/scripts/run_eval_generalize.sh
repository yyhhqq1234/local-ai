#!/usr/bin/env bash
# RE 真泛化测试：四档 × 12 条改写提问（去工具名提示）
#   基座 / 档1(1遍) / 档2(2遍) / 档3(3遍)
# 判据：命中率 >=70% 且 编造=0 且 L3 命中 >=2/4
set -u
cd "$(dirname "$0")/../.." || exit 1

PY=./train/.venv/Scripts/python.exe
[ -f "$PY" ] || { echo "[FATAL] venv 缺失"; exit 1; }

export PYTHONIOENCODING=utf-8
export HF_HUB_OFFLINE=1
export HF_HUB_DISABLE_SYMLINKS=1

OUTDIR=train/logs
mkdir -p "$OUTDIR" train/lines/9b-oxcoder/out
TS=$(date '+%Y%m%d-%H%M')

# 标签:adapter路径（空路径 = 基座）
CAND=(
  "基座:"
  "档1-1ep:train/lines/9b-oxcoder/out/re-stage1-fixed/final"
  "档2-2ep:train/lines/9b-oxcoder/out/re-r2-ckpt1400-snapshot"
  "档3-3ep:train/lines/9b-oxcoder/out/re-stage1-r2/final"
)

echo "=============================================================="
echo " RE 真泛化测试  $TS  （改写提问 · 去工具名 · 12 条）"
echo "=============================================================="

for item in "${CAND[@]}"; do
  tag="${item%%:*}"
  path="${item#*:}"
  if [ -n "$path" ] && [ ! -d "$path" ]; then
    echo "[SKIP] $tag → $path 不存在"
    continue
  fi
  echo ""
  echo "──────── $tag ────────"
  if [ -z "$path" ]; then
    "$PY" -u train/lines/_shared/scripts/eval_re_generalize.py \
        --adapter "" --out "train/lines/9b-oxcoder/out/eval-gen-${tag}-${TS}.json" \
        2>&1 | tee "$OUTDIR/eval-gen-${tag}-${TS}.log" | grep -vE "^Loading|^W1028" | tail -32 || true
  else
    "$PY" -u train/lines/_shared/scripts/eval_re_generalize.py \
        --adapter "$path" --out "train/lines/9b-oxcoder/out/eval-gen-${tag}-${TS}.json" \
        2>&1 | tee "$OUTDIR/eval-gen-${tag}-${TS}.log" | grep -vE "^Loading|^W1028" | tail -32 || true
  fi
done

echo ""
echo "=============================================================="
echo " 汇总对照（手填）："
echo "   标签      命中率   编造  L1  L2  L3"
echo "   基座      ?        ?     ?   ?   ?"
echo "   档1-1ep   ?        ?     ?   ?   ?"
echo "   档2-2ep   ?        ?     ?   ?   ?"
echo "   档3-3ep   ?        ?     ?   ?   ?"
echo " 日志 → $OUTDIR/eval-gen-*-${TS}.log"
echo " JSON → train/lines/9b-oxcoder/out/eval-gen-*-${TS}.json"
echo "=============================================================="
