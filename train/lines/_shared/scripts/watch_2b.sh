#!/usr/bin/env bash
# 2B 训练值守：每 10 分钟采一次（步数/loss/lr/步速/显存/温度/功率），写 train/logs/2b-watch.log
# 异常（NaN、显存>11.5G、温度>84、进程消失）立即打 ALERT 行
set -u
cd "$(dirname "$0")/../.." || exit 1
L=train/logs; W="$L/2b-watch.log"; TJ=train/lines/9b-oxcoder/out/2b-nsfw/train-log.jsonl
log(){ echo "$*" | tee -a "$W"; }
log "[WATCH] 启动 $(date '+%F %T')"

while :; do
  ts=$(date '+%F %T')
  if ! ps -ef | grep -q "[t]rain_qlora9b"; then
    log "[WATCH $ts] 训练进程已退出（收口或异常）→ 值守结束"
    break
  fi
  # 训练侧
  line=$(tail -1 "$TJ" 2>/dev/null)
  step=$(echo "$line" | sed -n 's/.*"step": *\([0-9]*\).*/\1/p')
  loss=$(echo "$line" | sed -n 's/.*"loss": *\([0-9.eE+-]*\).*/\1/p')
  lr=$(echo "$line" | sed -n 's/.*"learning_rate": *\([0-9.eE+-]*\).*/\1/p')
  # 步速（最近进度条）
  spd=$(tail -c 400 "$L/2b-train.log" 2>/dev/null | tr '\r' '\n' | grep -oE "[0-9.]+s/it" | tail -1)
  # GPU 侧
  gpu=$(nvidia-smi --query-gpu=utilization.gpu,power.draw,memory.used,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
  util=$(echo "$gpu" | cut -d, -f1); pw=$(echo "$gpu" | cut -d, -f2)
  mem=$(echo "$gpu" | cut -d, -f3); temp=$(echo "$gpu" | cut -d, -f4)
  eta=""
  if [ -n "${step:-}" ]; then
    rem=$((5545 - step)); [ "$rem" -lt 0 ] && rem=0
    s=${spd%s/it}; [ -z "$s" ] && s=3.2
    eta=$(awk -v r="$rem" -v s="$s" 'BEGIN{printf "%.1fh", r*s/3600}')
  fi
  log "[WATCH $ts] step=${step:-NA}/5545 loss=${loss:-NA} lr=${lr:-NA} 步速=${spd:-NA} ETA=${eta:-NA} GPU=${util:-NA}% ${pw:-NA}W ${mem:-NA}MiB ${temp:-NA}℃"
  # 告警
  case "${loss:-}" in *nan*|*NaN*|*inf*) log "[ALERT $ts] loss=$loss";; esac
  [ "${temp:-0}" -gt 84 ] 2>/dev/null && log "[ALERT $ts] 温度 ${temp}℃ > 84"
  [ "${mem:-0}" -gt 11500 ] 2>/dev/null && log "[ALERT $ts] 显存 ${mem}MiB 逼近上限"
  sleep 600
done
