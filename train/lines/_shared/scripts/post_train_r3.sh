#!/usr/bin/env bash
# r3 训练结束 → 自动评测 → 自动验收（一条龙，无人值守）
#
# 触发条件：train/lines/9b-oxcoder/out/re-stage1-r3/final/adapter_model.safetensors 出现
# 输出：
#   train/lines/9b-oxcoder/out/eval-r3-40cases.json     评测原始结果（3 档 × 40 条）
#   train/R3-ACCEPTANCE.md             验收报告
#   train/logs/r3-post-train.log       全过程日志
#
# 用法（后台）：
#   bash train/lines/_shared/scripts/post_train_r3.sh &
set -u
cd "$(dirname "$0")/../.." || exit 1

OUT=train/lines/9b-oxcoder/out/re-stage1-r3
FIN="$OUT/final/adapter_model.safetensors"
LOG=train/logs/r3-post-train.log
PY=train/.venv/Scripts/python.exe
mkdir -p train/logs

echo "[$(date +%H:%M:%S)] 开始守候 $FIN" >> "$LOG"

# ── 1 守候训练结束（最多 6 小时，每 30 s 一次）─────────────────
for i in $(seq 1 720); do
  if [ -f "$FIN" ]; then
    echo "[$(date +%H:%M:%S)] 训练完成，final 已生成" >> "$LOG"
    break
  fi
  if [ $((i % 20)) -eq 0 ]; then
    STEP=$(tail -1 "$OUT/train-log.jsonl" 2>/dev/null | sed -n 's/.*"step": *\([0-9]*\).*/\1/p')
    echo "[$(date +%H:%M:%S)] 守候中 try=$i step=${STEP:-?}" >> "$LOG"
  fi
  sleep 30
done

if [ ! -f "$FIN" ]; then
  echo "[$(date +%H:%M:%S)] 超时未等到 final，退出" >> "$LOG"
  exit 2
fi

# ★ 等训练进程真正释放显存 —— 否则评测加载 base+adapter 会 OOM
#   只看 final 文件不够：trainer.save_model 写完后进程还要收尾 10-30 s
#   判据：GPU used < 2500 MiB（训练时是 9.4 GB）
echo "[$(date +%H:%M:%S)] 等显存释放（训练时约 9.4 GB）" >> "$LOG"
for j in $(seq 1 90); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' \r')
  if [ -n "$USED" ] && [ "$USED" -lt 2500 ] 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] 显存已释放 used=${USED}MiB" >> "$LOG"
    break
  fi
  if [ $((j % 6)) -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] 等显存 try=$j used=${USED:-?}MiB" >> "$LOG"
  fi
  sleep 5
done
sleep 10   # 再让 CUDA context 完全销毁

# ── 2 评测（3 档 × 40 条；base 与 tier3 走缓存，r3 约 25 分钟）──
echo "[$(date +%H:%M:%S)] 启动评测" >> "$LOG"
$PY train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "base=,tier3=train/lines/9b-oxcoder/out/re-stage1-r2/final,r3=train/lines/9b-oxcoder/out/re-stage1-r3/final" \
    --max-new 300 --batch 1 \
    --out train/lines/9b-oxcoder/out/eval-r3-40cases.json >> "$LOG" 2>&1
echo "[$(date +%H:%M:%S)] 评测结束 rc=$?" >> "$LOG"

# ── 3 验收对照 ────────────────────────────────────────────────
if [ -f train/lines/9b-oxcoder/out/eval-r3-40cases.json ]; then
  $PY train/lines/_shared/scripts/compare_accept.py \
      --eval train/lines/9b-oxcoder/out/eval-r3-40cases.json \
      --new-label r3 --base-label tier3 \
      --out-md train/R3-ACCEPTANCE.md >> "$LOG" 2>&1
  echo "[$(date +%H:%M:%S)] 验收报告 → train/R3-ACCEPTANCE.md" >> "$LOG"
else
  echo "[$(date +%H:%M:%S)] 评测结果缺失，跳过验收" >> "$LOG"
fi

# ── 4 顺带跑多快照对比（1400 / 2000 / final）──────────────────
if [ -d train/lines/9b-oxcoder/out/re-r3-ckpt1400-snapshot ] && [ -d train/lines/9b-oxcoder/out/re-r3-ckpt2000-snapshot ]; then
  echo "[$(date +%H:%M:%S)] 启动快照对比" >> "$LOG"
  $PY train/lines/_shared/scripts/eval_multi_adapter.py \
      --adapters "r3-1400=train/lines/9b-oxcoder/out/re-r3-ckpt1400-snapshot,r3-2000=train/lines/9b-oxcoder/out/re-r3-ckpt2000-snapshot,r3-final=train/lines/9b-oxcoder/out/re-stage1-r3/final" \
      --max-new 300 --batch 1 \
      --out train/lines/9b-oxcoder/out/eval-r3-snapshots.json >> "$LOG" 2>&1
  echo "[$(date +%H:%M:%S)] 快照对比 → train/lines/9b-oxcoder/out/eval-r3-snapshots.json" >> "$LOG"
fi

echo "[$(date +%H:%M:%S)] 全部完成" >> "$LOG"
