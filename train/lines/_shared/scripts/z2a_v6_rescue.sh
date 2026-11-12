#!/usr/bin/env bash
# v6 抢救：训练在 step 800 因磁盘满中断（os error 112），但 ckpt-400/800 完好
#   先评这两档（每档约 17 min），若 cov≥0.60 即收口，不必重训
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/z2a-v6-rescue.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
log "================ v6 抢救评测启动 pid=$$ ================"

best=""; bestcov=-1
for ck in $(ls -dv "$OUT"/z-2a-v6/checkpoint-* 2>/dev/null | tail -2); do
  nm=$(basename "$ck")
  log "评测：$nm"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" --max-new 1200 \
    --out "$OUT/eval-2a-z2a-v6-$nm.json" >> "$LOG" 2>&1
  c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v6-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "  $nm cov=$c"
  if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
    best="$OUT/eval-2a-z2a-v6-$nm.json"; bestcov="$c"
  fi
done

if [ -n "$best" ]; then
  cp "$best" "$OUT/eval-2a-z2a-v6.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v6.json" --base "$OUT/eval-2a-r3-v2.json"; echo "rc=$?"; } \
    >> "$L/gate-z2a-v6.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | v6 抢救评测完成 · cov=$bestcov |" >> "$L/z-stages.md"
fi
log "================ v6 抢救评测结束 ================"
