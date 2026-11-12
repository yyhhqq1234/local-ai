#!/usr/bin/env bash
# 2A 趋势采样一次性快照（供 monitor-2a 每小时分析用）
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
OUT="train/logs/monitor-2a-snap-$(date +%Y%m%d-%H%M).txt"
{
  echo "=== TS ==="; date
  echo "=== WATCH LOG (last 12) ==="
  tail -12 train/logs/2a-watch.log 2>/dev/null || echo "NO-WATCH-LOG"
  echo "=== ALERT COUNT ==="
  grep -c ALERT train/logs/2a-watch.log 2>/dev/null || echo 0
  echo "=== AGG ==="
  C:/ProgramData/anaconda3/python.exe train/lines/_shared/scripts/monitor_2a_agg.py 2>&1
  echo "=== LOG TAIL 5 ==="
  tail -5 train/lines/9b-oxcoder/out/2a-stage/train-log.jsonl
  echo "=== GPU ==="
  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader
  echo "=== CKPTS ==="
  ls -d train/lines/9b-oxcoder/out/2a-stage/checkpoint-* 2>/dev/null | tr '\n' ' '
  echo
  echo "=== FINAL ==="
  ls -la train/lines/9b-oxcoder/out/2a-stage/final/ 2>/dev/null || echo "NO-FINAL"
  echo "=== PROC ==="
  wmic process where "name like '%python%'" get processid,commandline 2>/dev/null | grep -c train_qlora9b || echo "0"
} > "$OUT" 2>&1
echo "WROTE $OUT"
