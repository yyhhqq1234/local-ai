#!/usr/bin/env bash
# Z-2A v3：换长答数据源（v2 的 cov 卡在 48.13%，判定为数据内容不足）
#   数据 = kitty-v3-clean 的 2A 长答子集（1023 行，无 tool_call、带代码块、p50 402 / max 2599 字符）
#        + 原 eval-shape lite 1149 行（去重）→ 目标 cov ≥0.60
#   训练 = 基座直接训（不接 r3），2 epoch，lr 3e-5，三档 ckpt 选优
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out; MK="$L/.takeover"
LOG="$L/z2a-v3.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

log "================ Z-2A v3 启动 pid=$$ ================"

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v3.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, hashlib
def rows(p):
    for l in open(p, encoding="utf-8"):
        l = l.strip()
        if l:
            yield json.loads(l)
def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "assistant")
long2a = [r for r in rows("train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-clean.jsonl")
          if "tool_call" not in asst(r) and "```" in asst(r)]
lite = list(rows("train/lines/9b-oxcoder/data/agent-traj/traj-2a-lite.jsonl"))
seen, out = set(), []
for r in long2a + lite:
    a = asst(r)
    if "tool_call" in a:
        continue
    key = hashlib.md5(json.dumps(r.get("messages"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if key in seen:
        continue
    seen.add(key)
    out.append(r)
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v3.jsonl", "w", encoding="utf-8") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"[build] long2a={len(long2a)} + lite={len(lite)} → 去重后 {len(out)} 行")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

{ echo "=== notool gate $(date '+%F %T') ==="; \
  "$PY" train/lines/_shared/scripts/check_notool_gate.py "$DATA"; echo "rc=$?"; } >> "$L/gate-notool-z2a-v3.log" 2>&1
log "notool 门禁完成"

if [ ! -d "$OUT/z-2a-v3/final" ]; then
  log "训练开始：$(wc -l < "$DATA") 行 · 2 epoch · lr 3e-5 · 基座直训"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v3" \
    --ctx 2048 --epochs 2 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 300 --save-total-limit 6 >> "$L/z-2a-v3-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练：z-2a-v3/final 已存在"
fi

if [ -d "$OUT/z-2a-v3/final" ]; then
  log "评测：final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v3/final" \
    --max-new 1200 --out "$OUT/eval-2a-z2a-v3-final.json" >> "$LOG" 2>&1
  best="$OUT/eval-2a-z2a-v3-final.json"
  bestcov=$("$PY" -c "import json;print(json.load(open('$best',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "final cov=$bestcov"
  for ck in $(ls -d "$OUT"/z-2a-v3/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -3); do
    nm=$(basename "$ck")
    log "评测：$nm"
    "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" \
      --max-new 1200 --out "$OUT/eval-2a-z2a-v3-$nm.json" >> "$LOG" 2>&1
    c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v3-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
    log "  $nm cov=$c"
    if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
      best="$OUT/eval-2a-z2a-v3-$nm.json"; bestcov="$c"
    fi
  done
  cp "$best" "$OUT/eval-2a-z2a-v3.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v3.json" --base "$OUT/eval-2a-r3-v2.json"; \
    echo "rc=$?"; } >> "$L/gate-z2a-v3.log" 2>&1
  { echo "=== toolname gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_toolname_gate.py "$DATA"; echo "rc=$?"; } >> "$L/gate-toolname-z2a-v3.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-2A v3 完成 · z-2a-v3（cov=$bestcov） |" >> "$L/z-stages.md"
fi
log "================ Z-2A v3 结束 ================"
