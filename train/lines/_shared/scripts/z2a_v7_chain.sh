#!/usr/bin/env bash
# Z-2A v7（路线 A 收口尝试）：混合两路已证实有效的语料
#   证据：
#     v3（kitty 长答1023 + lite1149）→ cov 57.54% · code 0.875（代码块结构好，标识符覆盖不足）
#     v6（原生 OpenHands 轨迹，20%） → cov 46.25% · code 0.175（标识符丰富，缺 ``` 围栏）
#   处方：v3 全量 2172 + v6 原生 2000 子集（system 已统一 SYSTEM_2A）= 4172 行
#        两者互补：v6 补"任务标识符复述"，v3 保"代码块结构"
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/z2a-v7.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
log "================ Z-2A v7 启动 pid=$$ ================"

# 等 GPU / 显存
t0=$(date +%s)
while ps -ef | grep -qE "[e]val_2a|[t]rain_qlora9b"; do
  sleep 30; el=$(( $(date +%s) - t0 )); [ $((el % 300)) -lt 30 ] && log "等进程 … ${el}s"
  [ "$el" -gt 3600 ] && break
done
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 )); [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用中 … ${el}s"
  [ "$el" -gt 900 ] && { log "超 15min → 停 ninfer 接管"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10; break; }
  sleep 30
done

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v7.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, random
random.seed(20251031)
def rows(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
base = rows("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v3.jsonl")          # 2172：kitty长答 + lite
raw  = rows("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v6.jsonl")          # 15903：原生轨迹（system=SYSTEM_2A）
sub  = random.sample(raw, 2000)
out  = base + sub
random.shuffle(out)
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v7.jsonl", "w", encoding="utf-8") as f:
    for r in out: f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")
print(f"[build] v3 {len(base)} + v6 子集 {len(sub)} = {len(out)} 行")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

{ echo "=== notool gate $(date '+%F %T') ==="; "$PY" train/lines/_shared/scripts/check_notool_gate.py "$DATA"; echo "rc=$?"; } >> "$L/gate-notool-z2a-v7.log" 2>&1
{ echo "=== toolname gate $(date '+%F %T') ==="; "$PY" train/lines/_shared/scripts/check_toolname_gate.py "$DATA"; echo "rc=$?"; } >> "$L/gate-toolname-z2a-v7.log" 2>&1

if [ ! -d "$OUT/z-2a-v7/final" ]; then
  log "训练开始：$(wc -l < "$DATA") 行 · 1 epoch · lr 3e-5 · ctx 2048"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v7" \
    --ctx 2048 --epochs 1 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 300 --save-total-limit 5 >> "$L/z-2a-v7-train.log" 2>&1
  log "训练退出 rc=$?"
fi

if [ -d "$OUT/z-2a-v7/final" ]; then
  best="$OUT/eval-2a-z2a-v7-final.json"; bestcov=0
  log "评测：final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v7/final" --max-new 1200 --out "$best" >> "$LOG" 2>&1
  bestcov=$("$PY" -c "import json;print(json.load(open('$best',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "final cov=$bestcov"
  for ck in $(ls -dv "$OUT"/z-2a-v7/checkpoint-* 2>/dev/null | tail -2); do
    nm=$(basename "$ck")
    log "评测：$nm"
    "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" --max-new 1200 --out "$OUT/eval-2a-z2a-v7-$nm.json" >> "$LOG" 2>&1
    c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v7-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
    log "  $nm cov=$c"
    "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null && { best="$OUT/eval-2a-z2a-v7-$nm.json"; bestcov="$c"; }
  done
  cp "$best" "$OUT/eval-2a-z2a-v7.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v7.json" --base "$OUT/eval-2a-r3-v2.json"; echo "rc=$?"; } \
    >> "$L/gate-z2a-v7.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-2A v7 完成 · cov=$bestcov |" >> "$L/z-stages.md"
fi
log "================ Z-2A v7 结束 ================"
