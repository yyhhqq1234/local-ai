#!/usr/bin/env bash
# 2B v2 续训（分类迁移后从 checkpoint-2700 续）+ 门控评测
set -u
cd "$(dirname "$0")/../../.." || exit 1     # → 仓库根
PY=./train/.venv/Scripts/python.exe
L=train/logs; O=train/lines/9b-oxcoder/out; D=train/lines/9b-oxcoder/data; S=train/lines/_shared/scripts
LOG="$L/2b-v2-resume.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
log "================ 2B v2 续训启动 ================"
df -h /d | tail -1 | tee -a "$LOG"

# 显存闸门
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 )); [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用 … ${el}s"
  [ "$el" -gt 900 ] && { log "超 15min → 停 ninfer 接管"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10; break; }
  sleep 30
done

CKPT="$O/2b-nsfw-v2/checkpoint-2700"
log "续训：resume=$CKPT → out=$O/2b-nsfw-v2"
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
"$PY" -u "$S/train_qlora9b.py" \
  --base "train/lines/9b-oxcoder/models/OxCoder-9B" \
  --data "$D/nsfw-gated/train-2b-gated.jsonl" \
  --stage nsfw --lora-r 32 --lora-alpha 64 --out "$O/2b-nsfw-v2" --resume "$CKPT" \
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 300 --save-total-limit 8 >> "$L/2b-v2-resume-train.log" 2>&1
log "训练退出 rc=$?"

if [ -d "$O/2b-nsfw-v2/final" ]; then
  log "门控评测（val 85）"
  PYTHONIOENCODING=utf-8 "$PY" "$S/nsfw_gate_local.py" \
    --adapter "$O/2b-nsfw-v2/final" --val "$D/eval/val/nsfw-gate.jsonl" \
    --max-new 512 --out "$L/gate-local-2b-v2b.json" >> "$LOG" 2>&1
  log "门控评测 rc=$?（0=达标）"
fi
log "================ 2B v2 续训结束 ================"
