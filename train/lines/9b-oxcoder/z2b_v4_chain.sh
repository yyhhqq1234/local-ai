#!/usr/bin/env bash
# 2B 门控 v4 训练链（排在 Z-B v5 之后，单卡串行）
#
# 数据依据（2026-11-02 实测）：
#   评测集 85 条里 55 条共用 system=「模式：常规（未授权成人向内容）」
#     ├ gate-off    30 条 → 创作请求，应拒写
#     └ gate-trap 9 + gate-general 16 = 25 条 → 知识/技术问答，应正常答
#   v2 训练集带 system=常规 的 2593 条**全部是拒写**，ctl 又没配这个 system
#   → 模型学成「system=常规 ⇒ 喷拒写模板」，与 user 内容无关
#   → 实测 GateFPR 0.33 · TrapRefusal 1.00
#
# 处方 v4 = v3b + 3360 条「system=常规 下的正常回答」（A 知识 / B 技术 / C 概念讨论）
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
DATA="$D9/nsfw-gated/train-2b-gated-v4b-train-deleak.jsonl"
LOG="$L/2b-v4b.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ 2B v4 训练链启动 pid=$$ ================"
[ -f "$DATA" ] || { log "缺数据：$DATA → 中止"; exit 1; }
log "数据 $(wc -l < "$DATA") 行"

# ── 显存闸门：等前一条链（Z-B v5）跑完；只清 ninfer，绝不杀训练进程 ──
log "等待显存 <1500MiB（最多 12h）"
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 ))
  [ $((el % 600)) -lt 30 ] && log "显存 ${used}MiB 占用 … 已等 ${el}s"
  if [ $((el % 600)) -lt 30 ]; then
    if tasklist //FI "IMAGENAME eq ninfer-serve.exe" 2>/dev/null | grep -q ninfer-serve; then
      log "检测到 ninfer-serve → 停掉让位"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10
    fi
  fi
  [ "$el" -gt 43200 ] && { log "等待超 12h → 中止"; exit 1; }
  sleep 60
done

# ── 训练 ──
if [ ! -d "$OUT/2b-nsfw-v4/final" ]; then
  STEPS=$(( $(wc -l < "$DATA") / 4 ))
  log "训练开始：init=z-2a-v7 · ${STEPS} 步 · 1 epoch · lr 2e-5 · seed 42"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage nsfw \
    --init-adapter "$OUT/z-2a-v7/final" --out "$OUT/2b-nsfw-v4" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
    --lora-r 32 --lora-alpha 64 --lora-dropout 0.1 --weight-decay 0.01 \
    --optim adamw_torch --use-liger-ce \
    --save-steps 400 --save-total-limit 8 >> "$L/2b-v4-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "训练产物已存在，跳过"
fi

# ── 分片门控评测（85 条，每片 12 条，规避「跑约 20 条进程消失」）──
if [ -d "$OUT/2b-nsfw-v4/final" ]; then
  log "分片门控评测开始"
  bash train/lines/9b-oxcoder/_gate_shard.sh "$OUT/2b-nsfw-v4/final" v4 12 >> "$LOG" 2>&1
  log "分片评测 rc=$?"
fi

log "================ 2B v4 训练链结束 ================"
grep -A12 "门控指标" "$LOG" | tail -16
