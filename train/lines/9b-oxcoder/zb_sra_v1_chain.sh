#!/usr/bin/env bash
# Z-B SRA-v1：以拒绝方向消融版为基座，不用 r3 起点，直接训工具路由
#
# 依据（TASKPOINT §A14，2026-11-02 操作者决定）：
#   基座 SRA = OxCoder-9B-sra-g1.0（19 层 × down/o/out_proj 减去拒绝方向，移除能量 3.6%）
#   动态实测：能力无倒退（8 条全答、长度相当、SQL 题还更完整）
#
# 本次相对 v4 动了两个变量：
#   ① 基座  OxCoder-9B → OxCoder-9B-sra-g1.0
#   ② 起点  去掉 r3（r3 是在原版上训的，套到消融版可能冲突）
#
# 训完停，不自动评测（沿用操作者此前的要求）
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
BASE=train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0
DATA="$D9/_legacy/mix-z-re-v4.jsonl"
LOG="$L/zb-sra-v1.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B SRA-v1 启动 pid=$$ ================"
[ -d "$BASE" ] || { log "缺基座 $BASE → 中止"; exit 1; }
[ -f "$DATA" ] || { log "缺数据 $DATA → 中止"; exit 1; }
log "基座 $(basename "$BASE") · 数据 $(wc -l < "$DATA") 行 · 无 init-adapter"

# 基座完整性预检（分片权重必须有 index.json）
[ -f "$BASE/model.safetensors.index.json" ] && log "分片权重：index.json 存在（$(ls "$BASE"/model-*.safetensors 2>/dev/null | wc -l) 个分片）" \
  || log "⚠ 未找到 index.json，按单文件权重尝试加载"

# 单实例锁
LOCK="$L/.train.pid"
if [ -f "$LOCK" ]; then
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$OLDPID" ] && [ "$OLDPID" != "0" ] && kill -0 "$OLDPID" 2>/dev/null; then
    log "已有训练 pid=$OLDPID 在跑 → 退出"; exit 3
  fi
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
  [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用 … ${el}s"
  [ "$el" -gt 3600 ] && { log "等显存超 1h → 中止"; exit 1; }
  sleep 30
done

STEPS=$(( $(wc -l < "$DATA") / 4 ))
log "训练开始：基座=SRA · ${STEPS} 步 · 1 epoch · lr 2e-5 · seed 42 · 无 init-adapter"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
  --base "$BASE" --data "$DATA" --stage re \
  --out "$OUT/z-re-sra-v1" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 400 --save-total-limit 6 >> "$L/zb-sra-v1-train.log" 2>&1
log "训练退出 rc=$?"

if [ -d "$OUT/z-re-sra-v1/final" ]; then
  log "final 已生成：$OUT/z-re-sra-v1/final"
  ls "$OUT/z-re-sra-v1/final" | sed 's/^/    /' | tee -a "$LOG"
  log "【停止点】不自动评测，等操作者指令"
else
  log "【异常】未生成 final，检查 $L/zb-sra-v1-train.log"
fi
log "================ Z-B SRA-v1 结束（未评测）================"
