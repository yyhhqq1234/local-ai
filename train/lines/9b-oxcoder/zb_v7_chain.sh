#!/usr/bin/env bash
# Z-B v7：补 456 条「不该调工具时直接答」样本（v6 mix + v7 直接答）
#
# 依据（2026-11-02 深度分析）：
#   训练集里「授权书 / 三段式回包 / 八阶段 / 黑盒白盒」这类概念题样本 381 条，
#   100% 都输出了工具调用 —— 零条「直接答」。
#   评测 40 条里的 N01-N04 正是这类（expect 为空），v5 实测全错，占 10%。
#
# 本链**只训练，不评测**（操作者要求：训完停下来验证）
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
DATA="$D9/_legacy/mix-z-re-v7-train.jsonl"
LOG="$L/zb-v7.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B v7 启动 pid=$$ ================"
[ -f "$DATA" ] || { log "缺数据 $DATA → 中止"; exit 1; }
log "数据 $(wc -l < "$DATA") 行"

# 单实例锁（pidfile 版，git-bash 没有 flock）
LOCK="$L/.train.pid"
if [ -f "$LOCK" ]; then
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$OLDPID" ] && [ "$OLDPID" != "0" ] && kill -0 "$OLDPID" 2>/dev/null; then
    log "已有训练 pid=$OLDPID 在跑 → 本次退出"; exit 3
  fi
  log "旧锁残留 pid=$OLDPID 已死 → 清理"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
log "拿到训练锁 pid=$$"

# 显存闸门
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 ))
  [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用 … 已等 ${el}s"
  [ "$el" -gt 3600 ] && { log "等显存超 1h → 中止"; exit 1; }
  sleep 30
done

STEPS=$(( $(wc -l < "$DATA") / 4 ))
log "训练开始：init=r3 · ${STEPS} 步 · 1 epoch · lr 2e-5 · seed 42"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
  --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
  --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-v7" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 400 --save-total-limit 6 >> "$L/zb-v7-train.log" 2>&1
log "训练退出 rc=$?"

# 只做产物落盘确认，不评测（等操作者指令）
if [ -d "$OUT/z-re-v7/final" ]; then
  log "final 已生成：$OUT/z-re-v7/final"
  ls "$OUT/z-re-v7/final" | sed 's/^/    /' | tee -a "$LOG"
  log "【停止点】按操作者要求，训练完成后停在这里，不自动评测"
else
  log "【异常】未生成 final，检查 $L/zb-v7-train.log"
fi
log "================ Z-B v7 结束（未评测）================"
