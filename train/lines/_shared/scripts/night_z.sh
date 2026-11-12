#!/usr/bin/env bash
# 夜间链：Z-B（RE + 调用范式）→ 评测 → Z-2A v2（3 epoch）→ 评测 → 汇总
# 无人值守；每步日志分别落盘，任何一步失败继续下一步（不中断整链）
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs

run_step() {   # $1=名字  $2...=命令
  local name="$1"; shift
  echo "[$(date '+%F %T')] ==== $name 开始 ====" >> "$L/night-z.log"
  "$@" >> "$L/night-z.log" 2>&1
  local rc=$?
  echo "[$(date '+%F %T')] ==== $name 结束 rc=$rc ====" >> "$L/night-z.log"
  return 0
}

# ① Z-B：r3 + 调用范式（6069 步 ≈ 3.7h）
run_step "Z-B 训练" bash train/lines/_shared/scripts/run_z_re.sh

# ② Z-B 评测：RE 40 条（r3 对照）+ 门禁
run_step "Z-B RE 评测" "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
  --adapters "r3=train/lines/9b-oxcoder/out/re-stage1-r3/final,zre=train/lines/9b-oxcoder/out/z-re/final" \
  --max-new 300 --batch 1 --out train/lines/9b-oxcoder/out/eval-re-zre.json

# ③ Z-2A v2：3 epoch（864 步，补齐 cov）
run_step "Z-2A v2 训练" env DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl OUTDIR=train/lines/9b-oxcoder/out/z-2a-v2 \
  bash -c "$PY -u train/lines/_shared/scripts/train_qlora9b.py --base train/lines/9b-oxcoder/models/OxCoder-9B \
    --data train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl --stage re --out train/lines/9b-oxcoder/out/z-2a-v2 \
    --ctx 2048 --epochs 3 --lr 3e-5 --ga 4 --bs 1 --optim adamw_torch --use-liger-ce \
    --lora-dropout 0.1 --weight-decay 0.01 --save-steps 200 --save-total-limit 6"

# ④ Z-2A v2 评测 + 机制门禁
run_step "Z-2A v2 评测" "$PY" train/lines/_shared/scripts/eval_2a_code.py \
  --adapter train/lines/9b-oxcoder/out/z-2a-v2/final --max-new 1200 --out train/lines/9b-oxcoder/out/eval-2a-z2a-v2.json
run_step "Z-2A v2 门禁" "$PY" train/lines/_shared/scripts/check_eval_gate.py \
  train/lines/9b-oxcoder/out/eval-2a-z2a-v2.json --base train/lines/9b-oxcoder/out/eval-2a-r3-v2.json

echo "[$(date '+%F %T')] 夜间链全部结束" >> "$L/night-z.log"
