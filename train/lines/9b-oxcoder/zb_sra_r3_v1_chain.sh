#!/usr/bin/env bash
# Z-B SRA-r3-v1（R2）：SRA 基座 + 保留 r3 起点，唯一变量 = 基座
#
# 对比依据（2026-11-02 21:44 实测）：
#   zbv4 = OxCoder-9B（原版）      + r3 + 7608 行  → 30/40（75.0%）
#   sra1 = OxCoder-9B-sra-g1.0     + 无 + 7608 行  → 15/40（37.5%）← 去掉 r3 崩了
#
# 本次 = OxCoder-9B-sra-g1.0 + r3 + 7608 行
#   相对 v4 只改基座（单变量）；相对 sra1 只加回 r3
#
# 风险：r3 是在原版上训的，套到消融版上可能与消融方向冲突。
#      若训练早期出现 loss 不降 / NaN / 参数不匹配，立即停并记录。
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
BASE=train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0
INIT="$OUT/re-stage1-r3/final"
DATA="$D9/_legacy/mix-z-re-v4.jsonl"
LOG="$L/zb-sra-r3-v1.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B SRA-r3-v1（R2）启动 pid=$$ ================"
[ -d "$BASE" ] || { log "缺基座 $BASE"; exit 1; }
[ -d "$INIT" ] || { log "缺 r3 adapter $INIT"; exit 1; }
[ -f "$DATA" ] || { log "缺数据 $DATA"; exit 1; }
log "基座=SRA · 起点=r3 · 数据 $(wc -l < "$DATA") 行（唯一变量：基座）"

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
log "训练开始：SRA + r3 · ${STEPS} 步 · lr 2e-5 · seed 42"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
  --base "$BASE" --data "$DATA" --stage re \
  --init-adapter "$INIT" --out "$OUT/z-re-sra-r3-v1" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 400 --save-total-limit 6 >> "$L/zb-sra-r3-v1-train.log" 2>&1
log "训练退出 rc=$?"

if [ -d "$OUT/z-re-sra-r3-v1/final" ]; then
  log "final 已生成"
  log "【停止点】不自动评测，等操作者指令"
else
  log "【异常】未生成 final —— 可能是 r3 与消融版冲突，检查 $L/zb-sra-r3-v1-train.log"
  grep -iE "error|mismatch|nan|traceback" "$L/zb-sra-r3-v1-train.log" 2>/dev/null | tail -5 | tee -a "$LOG"
fi
log "================ Z-B SRA-r3-v1 结束 ================"
