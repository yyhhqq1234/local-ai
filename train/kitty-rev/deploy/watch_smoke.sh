#!/usr/bin/env bash
# watch_smoke.sh —— 后台轮询云端 27B smoke 训练日志（不阻塞前台）
# 用法: bash watch_smoke.sh [轮询次数=90] [间隔秒=45]
PY='C:/ProgramData/anaconda3/python.exe'
cd "$(dirname "$0")" || exit 1
OUT=../logs/cloud-smoke-watch.log
N=${1:-90}
SLEEP=${2:-45}
: > "$OUT"
for i in $(seq 1 "$N"); do
  echo "===== poll $i $(date '+%H:%M:%S') =====" >> "$OUT"
  MSYS2_ARG_CONV_EXCL='*' "$PY" remote.py --timeout 40 --cmd \
    "tr '\r' '\n' < /root/smoke.log | grep -aE \"'loss'|train_runtime|CUDA out|Traceback\" | tail -3; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader" \
    >> "$OUT" 2>&1
  if grep -qaE "train_runtime|CUDA out of memory|Traceback" "$OUT"; then
    echo "[watcher] terminal condition hit at poll $i" >> "$OUT"
    break
  fi
  sleep "$SLEEP"
done
echo "[watcher] exit" >> "$OUT"
