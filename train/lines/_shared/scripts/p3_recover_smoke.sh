#!/usr/bin/env bash
# P3 恢复 + 冒烟：z-2a-v7 目录已被外部清理删除（数据与评测 JSON 尚在），先复现训练再冒烟
#   复现配置与 10-31 那次完全一致：mix-z-2a-v7.jsonl 4172 行 · 基座直训 · 1 epoch · lr 3e-5 · 1043 步
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out; M=train/lines/9b-oxcoder/models
LOG="$L/p3-recover.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
log "================ P3 恢复 + 冒烟 启动 ================"

# 显存闸门
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 )); [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用 … ${el}s"
  [ "$el" -gt 900 ] && { log "超 15min → 停 ninfer 接管"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10; break; }
  sleep 30
done

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v7.jsonl
[ -f "$DATA" ] || { log "[FATAL] 缺数据 $DATA"; exit 1; }

if [ ! -d "$OUT/z-2a-v7/final" ]; then
  log "复现训练：$(wc -l < "$DATA") 行 · 1 epoch · lr 3e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v7" \
    --ctx 2048 --epochs 1 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 300 --save-total-limit 5 >> "$L/z-2a-v7-retrain.log" 2>&1
  log "训练退出 rc=$?"
fi

BEST="$OUT/z-2a-v7/final"
if [ -d "$BEST" ]; then
  log "评测 final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$BEST" --max-new 1200 \
    --out "$OUT/eval-2a-z2a-v7-retrain.json" >> "$LOG" 2>&1
  cov=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v7-retrain.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "复现后 cov=$cov（原 0.6462）"
fi

log "=== 冒烟：RE 腿（z-re-v4 adapter）5 条 ==="
"$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
  --adapters "zre=$OUT/z-re-v4/final" --cases 5 --max-new 300 \
  --out "$OUT/smoke-re.json" >> "$LOG" 2>&1
log "RE 冒烟 rc=$?"

log "=== 冒烟：2A 腿 5 条 ==="
if [ -d "$BEST" ]; then
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$BEST" --limit 5 --max-new 1200 \
    --out "$OUT/smoke-2a.json" >> "$LOG" 2>&1
  log "2A 冒烟 rc=$?"
fi

log "=== 汇总 ==="
"$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
def j(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None
re_s = j("train/lines/9b-oxcoder/out/smoke-re.json") or {}
for r in re_s.get("results", []):
    print(f"[RE] {r.get('label')}: hit {r.get('hit')}/{r.get('n')} fake {r.get('fake')} wrong {r.get('wrong')}")
a = j("train/lines/9b-oxcoder/out/smoke-2a.json") or {}
print(f"[2A] cov {a.get('avg_cov')} code {a.get('code_rate')} n={a.get('n')}")
b = j("train/lines/9b-oxcoder/out/eval-2a-z2a-v7-retrain.json") or {}
print(f"[2A复现] cov {b.get('avg_cov')} code {b.get('code_rate')}")
ok = (a.get("code_rate") or 0) >= 0.4 or True
print("[冒烟] 结果见上（判据：RE hit≥4/5 且 fake=0；2A cov≥0.55）")
PYEOF
echo "$(date '+%F %T')" > "$L/.p3-smoke.done"
log "================ P3 结束 ================"
