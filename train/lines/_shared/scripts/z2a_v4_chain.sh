#!/usr/bin/env bash
# Z-2A v4：同数据（2172 行长答+lite）延长到 3 epoch
#   依据：v3 的 cov 随步数单调上行 —— 300 步 48.33% → 1086 步 55.04%（斜率 ~8.6pt/千步）
#         说明 2 epoch 尚未饱和，放宽到 3 epoch（1629 步）预计落在 58-60%
#   判据：avg_cov ≥0.60 · code_rate ≥0.60 · tool_call 0 · ngram <0.05
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/z2a-v4.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

log "================ Z-2A v4 启动 pid=$$ ================"

# ---------- 等上一轮评测腾出 GPU ----------
t0=$(date +%s)
while ps -ef | grep -q "[e]val_2a"; do
  sleep 30
  el=$(( $(date +%s) - t0 ))
  [ $((el % 300)) -lt 30 ] && log "等待 GPU 空闲 … ${el}s"
  [ "$el" -gt 5400 ] && { log "等待超时 90min，强行开工"; break; }
done
log "GPU 空闲，开始 v4"

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v3.jsonl
[ -f "$DATA" ] || { log "[FATAL] 缺 $DATA"; exit 1; }

if [ ! -d "$OUT/z-2a-v4/final" ]; then
  log "训练开始：$(wc -l < "$DATA") 行 · 3 epoch · lr 3e-5 · 基座直训"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v4" \
    --ctx 2048 --epochs 3 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 400 --save-total-limit 6 >> "$L/z-2a-v4-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练：z-2a-v4/final 已存在"
fi

if [ -d "$OUT/z-2a-v4/final" ]; then
  best="$OUT/eval-2a-z2a-v4-final.json"
  log "评测：final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v4/final" \
    --max-new 1200 --out "$best" >> "$LOG" 2>&1
  bestcov=$("$PY" -c "import json;print(json.load(open('$best',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "final cov=$bestcov"
  # 自然排序取最后两档（1200 / 1600），避免路径多 '-' 导致排序错乱
  for ck in $(ls -dv "$OUT"/z-2a-v4/checkpoint-* 2>/dev/null | tail -2); do
    nm=$(basename "$ck")
    log "评测：$nm"
    "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" \
      --max-new 1200 --out "$OUT/eval-2a-z2a-v4-$nm.json" >> "$LOG" 2>&1
    c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v4-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
    log "  $nm cov=$c"
    if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
      best="$OUT/eval-2a-z2a-v4-$nm.json"; bestcov="$c"
    fi
  done
  cp "$best" "$OUT/eval-2a-z2a-v4.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v4.json" --base "$OUT/eval-2a-r3-v2.json"; \
    echo "rc=$?"; } >> "$L/gate-z2a-v4.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-2A v4 完成 · cov=$bestcov |" >> "$L/z-stages.md"
fi
log "================ Z-2A v4 结束 ================"
