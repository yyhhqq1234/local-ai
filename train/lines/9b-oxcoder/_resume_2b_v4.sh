#!/usr/bin/env bash
# 2B v4 续训（从 checkpoint-6400 续到 8043）+ 分片门控评测
#
# 崩溃背景（2026-11-02 11:21:43）：
#   训练跑到 6552/8043（81%）时静默退出 rc=1，无 traceback = 被系统强杀
#   根因：Z-B v6 被重复启动两次（同秒、同 data/out），两个 9B 训练抢 12G 显存，
#         2B v4 被挤死（v6 自身也掉到 186 s/it 的换页速度）
#   处置：双实例已清，本脚本带单实例锁，杜绝重复启动
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
DATA="$D9/nsfw-gated/train-2b-gated-v4-train.jsonl"
LOG="$L/2b-v4-resume.log"
LOCK="$L/.train.lock"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# ── 单实例锁（pidfile 版：git-bash 没有 flock）──
LOCK="$L/.train.pid"
if [ -f "$LOCK" ]; then
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$OLDPID" ] && [ "$OLDPID" != "0" ] && kill -0 "$OLDPID" 2>/dev/null; then
    log "已有训练 pid=$OLDPID 在跑（$LOCK）→ 本次退出"
    exit 3
  fi
  log "旧锁残留 pid=$OLDPID 已死 → 清理"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
log "拿到训练锁 pid=$$"

log "================ 2B v4 续训启动 ================"
[ -f "$DATA" ] || { log "缺数据 $DATA"; exit 1; }

CKPT="$OUT/2b-nsfw-v4/checkpoint-6400"
[ -d "$CKPT" ] || { log "缺 checkpoint $CKPT"; exit 1; }
log "续训：resume=$CKPT → out=$OUT/2b-nsfw-v4"

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

PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
  --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage nsfw \
  --init-adapter "$OUT/z-2a-v7/final" --out "$OUT/2b-nsfw-v4" --resume "$CKPT" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --lora-r 32 --lora-alpha 64 --lora-dropout 0.1 --weight-decay 0.01 \
  --optim adamw_torch --use-liger-ce \
  --save-steps 400 --save-total-limit 8 >> "$L/2b-v4-resume-train.log" 2>&1
log "训练退出 rc=$?"

if [ -d "$OUT/2b-nsfw-v4/final" ]; then
  log "分片门控评测开始（8 片 × 12 条 / 85 条）"
  bash train/lines/9b-oxcoder/_gate_shard.sh "$OUT/2b-nsfw-v4/final" v4 12 >> "$LOG" 2>&1
  log "评测 rc=$?"
  grep -A10 "门控指标" "$LOG" | tail -14
else
  log "无 final，跳过评测"
fi
log "================ 2B v4 续训结束 ================"
