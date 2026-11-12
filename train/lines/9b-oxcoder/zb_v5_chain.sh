#!/usr/bin/env bash
# Z-B v5：把工具选择准确率从 75% 拉到 ≥90%
#
# 依据 eval-re-zbv4.json 的 10 条非命中，病根三类：
#   P1 同族/跨族混选  init↔drv · ida↔ghidra · settings↔reverse_add_target
#                     trail↔reverse_add_obs · ce(W|)↔prot · dualview 拆成三连
#   P2 漏工具前缀    只发裸 OP（W|0x..）不写 kitty_ce op=
#   P3 多工具堆叠    一次罗列 4 个工具，判定取首个即错
#
# 处方：kitty-v5-contrast.jsonl（318 条定向对比样本，全部只用 catalog 真实工具/action）
#       合入训练集并重复 2 份提权（≈8%）
set -u
cd "$(dirname "$0")/../../.." || exit 1        # → 仓库根
PY=./train/.venv/Scripts/python.exe
L=train/logs
OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
LOG="$L/zb-v5.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B v5 启动 pid=$$ ================"

# ── 1 合并训练数据 ─────────────────────────────────────────────
MIX="$D9/_legacy/mix-z-re-v5-train.jsonl"
if [ ! -f "$MIX" ]; then
  PYTHONIOENCODING=utf-8 "$PY" - <<'PYEOF' 2>&1 | tee -a "$LOG"
import io, json, random, os
random.seed(20251102)
src = "train/lines/9b-oxcoder/data/_legacy/mix-z-re-v4.jsonl"
add = "train/lines/9b-oxcoder/data/kitty-reverse/kitty-v5-strong.jsonl"
dst = "train/lines/9b-oxcoder/data/_legacy/mix-z-re-v5-train.jsonl"
base = [l for l in io.open(src, encoding="utf-8") if l.strip()]
extra = [l for l in io.open(add, encoding="utf-8") if l.strip()]
rows = base + extra               # strong 内部已按功能域+实测错点提权
random.shuffle(rows)
io.open(dst, "w", encoding="utf-8").writelines(rows)
print(f"[build] base={len(base)} + contrast={len(extra)}x2 → {len(rows)} 行 → {dst}")
PYEOF
  log "数据已建：$MIX"
else
  log "数据已存在：$MIX（$(wc -l < "$MIX") 行）"
fi

# ── 2 显存闸门（等分片评测 / ninfer 让位） ─────────────────────
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 )); [ $((el % 120)) -lt 30 ] && log "显存 ${used}MiB 占用 … ${el}s"
  [ "$el" -gt 900 ] && { log "超 15min → 停 ninfer 接管"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10; break; }
  sleep 30
done

# ── 3 训练 ─────────────────────────────────────────────────────
if [ ! -d "$OUT/z-re-v5/final" ]; then
  log "训练开始：init=r3 · $(wc -l < "$MIX") 行 · 1 epoch · lr 2e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$MIX" --stage re \
    --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-v5" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 300 --save-total-limit 6 >> "$L/zb-v5-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "训练产物已存在，跳过训练"
fi

# ── 4 评测 40 条固定集 ─────────────────────────────────────────
if [ -d "$OUT/z-re-v5/final" ]; then
  log "评测开始（r3 + zbv4 双对照 + zbv5）"
  PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "r3=$OUT/re-stage1-r3/final,zbv4=$OUT/z-re-v4/final,zbv5=$OUT/z-re-v5/final" \
    --max-new 300 --batch 1 --out "$OUT/eval-re-zbv5.json" >> "$L/zb-v5-eval.log" 2>&1
  log "评测 rc=$?"
fi

log "================ Z-B v5 结束 ================"
tail -25 "$LOG"
