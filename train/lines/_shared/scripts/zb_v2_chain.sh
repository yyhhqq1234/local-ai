#!/usr/bin/env bash
# Z-B v2 补强链：等 2A 主链 STEP6 落定 → r3 + 仅调用范式（600 行，2 epoch，lr 1.5e-5）
#  动机：zre（r3 全量重训 24274 行）编造=0 但 hit 30→28、noarg 3→6 = r3 参数能力被冲掉
#        只喂新增 600 行（占 r3 的 2.4%），既补范例又不覆盖 r3
#  产物：train/lines/9b-oxcoder/out/z-re-cov/final、eval-re-zbv2.json（合并进 eval-re-zre.json 供汇总）
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out; MK="$L/.takeover"
LOG="$L/zb-v2.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

log "================ Z-B v2 补强链启动 pid=$$ ================"

# ---------- 等主链 STEP6 落定 ----------
t0=$(date +%s)
while [ ! -f "$MK/step6.done" ]; do
  sleep 30
  el=$(( $(date +%s) - t0 ))
  [ $((el % 600)) -lt 30 ] && log "等待主链 STEP6 … ${el}s"
  [ "$el" -gt 14400 ] && { log "等 STEP6 超时 4h，直接开工"; break; }
done
log "主链已完成，开始 Z-B v2"

# ---------- 训练：r3 + 仅范式 600 行 ----------
DATA=train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-aug.jsonl
if [ ! -d "$OUT/z-re-cov/final" ]; then
  log "训练开始：init=r3 · data=$DATA(600) · 2 epoch · lr 1.5e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
    --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-cov" \
    --ctx 2048 --epochs 2 --lr 1.5e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 150 --save-total-limit 4 >> "$L/z-re-cov-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练：z-re-cov/final 已存在"
fi

# ---------- 评测：r3 对照 + zbv2 ----------
if [ -d "$OUT/z-re-cov/final" ]; then
  log "评测开始（r3 对照 + zbv2）"
  "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "r3=$OUT/re-stage1-r3/final,zbv2=$OUT/z-re-cov/final" \
    --max-new 300 --batch 1 --out "$OUT/eval-re-zbv2.json" >> "$LOG" 2>&1
  log "评测退出 rc=$?"

  # 合并：把 zbv2 结果并入 eval-re-zre.json（保留原 zre 条目做三方对比）
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
p = "train/lines/9b-oxcoder/out/eval-re-zre.json"; q = "train/lines/9b-oxcoder/out/eval-re-zbv2.json"
if os.path.exists(q):
    a = json.load(open(p, encoding="utf-8")); b = json.load(open(q, encoding="utf-8"))
    rows = {r["label"]: r for r in a["results"]}
    for r in b["results"]:
        rows[r["label"]] = r
    order = ["r3", "zre", "zbv2"]
    a["results"] = [rows[k] for k in order if k in rows] + [v for k, v in rows.items() if k not in order]
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[merge] eval-re-zre.json 现有:", list(rows))
PYEOF

  log "重新汇总"
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总退出 rc=$?"
  echo "| $(date '+%F %T') | Z-B v2 补强完成 · z-re-cov/final |" >> "$L/z-stages.md"
else
  log "训练产物缺失，跳过评测"
fi
log "================ Z-B v2 补强链结束 ================"
