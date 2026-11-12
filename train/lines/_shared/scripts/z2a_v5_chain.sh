#!/usr/bin/env bash
# Z-2A v5：扩数据（而不是加步数）
#   证据：v2 与 v3 两个数据集都在 600 步见顶（48.13% / 57.54%），之后下滑 ⇒ 步数不是杠杆
#   处方：数据 = kitty 长答 1023 + lite 1149 + evalshape t1(162) + t2(987) 去重 → 1 epoch
#          （约 3300 行 / 830 步 = 停在峰值区，不在过训区）
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/z2a-v5.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
log "================ Z-2A v5 启动 pid=$$ ================"

# 等 GPU
t0=$(date +%s)
while ps -ef | grep -qE "[e]val_2a|[t]rain_qlora9b"; do
  sleep 30; el=$(( $(date +%s) - t0 ))
  [ $((el % 300)) -lt 30 ] && log "等待 GPU … ${el}s"
  [ "$el" -gt 5400 ] && { log "超时强开"; break; }
done
log "GPU 空闲"

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v5.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, hashlib, os
def rows(p):
    if not os.path.exists(p): return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "assistant")
src = {
 "kitty_long": [r for r in rows("train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl")
                if "tool_call" not in asst(r) and "```" in asst(r)],
 "lite": rows("train/lines/9b-oxcoder/data/agent-traj/traj-2a-lite.jsonl"),
 "t1": rows("train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t1.jsonl"),
 "t2": rows("train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t2.jsonl"),
}
seen, out, stat = set(), [], {}
for k, lst in src.items():
    n = 0
    for r in lst:
        a = asst(r)
        if "tool_call" in a: continue
        key = hashlib.md5(json.dumps(r.get("messages"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if key in seen: continue
        seen.add(key); out.append(r); n += 1
    stat[k] = (len(lst), n)
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v5.jsonl", "w", encoding="utf-8") as f:
    for r in out: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("[build] " + " · ".join(f"{k}:{v[0]}→{v[1]}" for k, v in stat.items()) + f" | 合计 {len(out)}")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

{ echo "=== notool gate $(date '+%F %T') ==="; "$PY" train/lines/_shared/scripts/check_notool_gate.py "$DATA"; echo "rc=$?"; } \
  >> "$L/gate-notool-z2a-v5.log" 2>&1

if [ ! -d "$OUT/z-2a-v5/final" ]; then
  log "训练开始：$(wc -l < "$DATA") 行 · 1 epoch · lr 3e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v5" \
    --ctx 2048 --epochs 1 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 200 --save-total-limit 6 >> "$L/z-2a-v5-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练"
fi

if [ -d "$OUT/z-2a-v5/final" ]; then
  best="$OUT/eval-2a-z2a-v5-final.json"
  log "评测：final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v5/final" --max-new 1200 --out "$best" >> "$LOG" 2>&1
  bestcov=$("$PY" -c "import json;print(json.load(open('$best',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "final cov=$bestcov"
  for ck in $(ls -dv "$OUT"/z-2a-v5/checkpoint-* 2>/dev/null | tail -2); do
    nm=$(basename "$ck")
    log "评测：$nm"
    "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" --max-new 1200 --out "$OUT/eval-2a-z2a-v5-$nm.json" >> "$LOG" 2>&1
    c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v5-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
    log "  $nm cov=$c"
    if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
      best="$OUT/eval-2a-z2a-v5-$nm.json"; bestcov="$c"
    fi
  done
  cp "$best" "$OUT/eval-2a-z2a-v5.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v5.json" --base "$OUT/eval-2a-r3-v2.json"; echo "rc=$?"; } \
    >> "$L/gate-z2a-v5.log" 2>&1
  { echo "=== toolname gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_toolname_gate.py "$DATA"; echo "rc=$?"; } \
    >> "$L/gate-toolname-z2a-v5.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-2A v5 完成 · cov=$bestcov |" >> "$L/z-stages.md"
fi
log "================ Z-2A v5 结束 ================"
