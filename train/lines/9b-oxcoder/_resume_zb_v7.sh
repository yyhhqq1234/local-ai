#!/usr/bin/env bash
# Z-B v7 resume：从 checkpoint-1600 续到 2659，完成后停（不评测）
#
# 崩溃记录（2026-11-02 16:13:41）：
#   1894/2659 步 · 无 traceback · 无 error · 进程静默消失
#   同时 loss 出现异常低值 0.15-0.44（v4 是 1.48）→ 过拟合信号
#   checkpoint-1600 可用
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
DATA="$D9/_legacy/mix-z-re-v7-train.jsonl"
CKPT="$OUT/z-re-v7/checkpoint-1600"
LOG="$L/zb-v7-resume.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B v7 续训启动 pid=$$ ================"
[ -d "$CKPT" ] || { log "缺 checkpoint $CKPT"; exit 1; }

LOCK="$L/.train.pid"
if [ -f "$LOCK" ]; then
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$OLDPID" ] && [ "$OLDPID" != "0" ] && kill -0 "$OLDPID" 2>/dev/null; then
    log "已有训练 pid=$OLDPID 在跑 → 退出"; exit 3
  fi
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
log "拿到锁 pid=$$ · resume=$CKPT"

t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 ))
  [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用 … ${el}s"
  [ "$el" -gt 3600 ] && { log "等显存超 1h → 中止"; exit 1; }
  sleep 30
done

log "续训：1600 → 2659（1059 步）"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
  --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
  --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final \
  --out "$OUT/z-re-v7" --resume "$CKPT" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 400 --save-total-limit 6 >> "$L/zb-v7-resume-train.log" 2>&1
log "训练退出 rc=$?"

if [ -d "$OUT/z-re-v7/final" ]; then
  log "final 已生成"
  ls "$OUT/z-re-v7/final" | sed 's/^/    /' | tee -a "$LOG"
  log "【停止点】不自动评测，等操作者指令"
else
  log "【异常】无 final，检查 $L/zb-v7-resume-train.log"
fi
log "================ Z-B v7 续训结束 ================"
