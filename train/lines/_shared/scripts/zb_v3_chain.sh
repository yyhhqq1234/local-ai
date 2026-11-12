#!/usr/bin/env bash
# Z-B v3：r3 + 30% 主力数据 + 调用范式（验证「补范式必须带主力数据、且 lr 要小」）
#   依据：zre（全量 24274 + 600 范式, lr 3e-5, 1ep）= hit28/acc70/fake0（轻微掉点）
#         zbv2（仅 600 范式, lr 1.5e-5, 2ep）   = hit21/acc52.5/fake4（语义崩）
#   假设：主力数据在场时语义不崩，lr 减半可保住 hit 30；范式数据量不变即可维持 fake 0
#   数据：kitty-v3-clean 随机 7000 行（seed 20251031）+ 600 范式 → mix-z-re-v3.jsonl
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/zb-v3.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

log "================ Z-B v3 启动 pid=$$ ================"

# ---------- 建数据（幂等） ----------
DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-re-v3.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, random
random.seed(20251031)
main = [l for l in open("train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl", encoding="utf-8")]
cov  = [l for l in open("train/lines/9b-oxcoder/data/agent-traj/kitty-callcoverage-aug.jsonl", encoding="utf-8")]
sub = random.sample(main, 7000)
rows = sub + cov
random.shuffle(rows)
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-re-v3.jsonl", "w", encoding="utf-8") as f:
    f.writelines(rows)
tc = sum(1 for r in cov if "tool_call" in r)
print(f"[build] main={len(main)} 取 {len(sub)} + cov={len(cov)} = {len(rows)} 行（cov 含 tool_call {tc}）")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

# ---------- 训练 ----------
if [ ! -d "$OUT/z-re-v3/final" ]; then
  log "训练开始：init=r3 · 7000+600 行 · 1 epoch · lr 2e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
    --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-v3" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 400 --save-total-limit 6 >> "$L/z-re-v3-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练：z-re-v3/final 已存在"
fi

# ---------- 评测 + 合并 + 重算 ----------
if [ -d "$OUT/z-re-v3/final" ]; then
  log "评测开始（r3 对照 + zbv3）"
  "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "r3=$OUT/re-stage1-r3/final,zbv3=$OUT/z-re-v3/final" \
    --max-new 300 --batch 1 --out "$OUT/eval-re-zbv3.json" >> "$LOG" 2>&1
  log "评测退出 rc=$?"

  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
p = "train/lines/9b-oxcoder/out/eval-re-zre.json"; q = "train/lines/9b-oxcoder/out/eval-re-zbv3.json"
if os.path.exists(q):
    a = json.load(open(p, encoding="utf-8")); b = json.load(open(q, encoding="utf-8"))
    rows = {r["label"]: r for r in a["results"]}
    for r in b["results"]:
        rows[r["label"]] = r
    order = ["r3", "zre", "zbv2", "zbv3"]
    a["results"] = [rows[k] for k in order if k in rows] + [v for k, v in rows.items() if k not in order]
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[merge] 现有:", list(rows))
PYEOF

  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-B v3 完成 · z-re-v3/final |" >> "$L/z-stages.md"
fi
log "================ Z-B v3 结束 ================"
