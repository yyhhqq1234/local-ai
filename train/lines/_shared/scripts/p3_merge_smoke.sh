#!/usr/bin/env bash
# P3：两份 adapter 各自 merge 进 bf16 基座 + 冒烟（不合并成一份！方案 Z 保持分离）
#   合并工具：train/lines/_shared/scripts/local_merge_lora.py（分片级，RAM<6GB）
#   冒烟：从评测集取前 5 条，比对 merged 与 adapter 输出一致性与判据
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out; M=train/lines/9b-oxcoder/models
LOG="$L/p3-merge-smoke.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ P3 merge + 冒烟 启动 ================"
df -h /d | tail -1 | tee -a "$LOG"

merge_one() {  # $1=adapter  $2=目标目录
  local ad="$1" dst="$2"
  if [ -f "$dst/model.safetensors" ] || ls "$dst"/*.safetensors >/dev/null 2>&1; then
    log "跳过 merge：$dst 已存在"
    return 0
  fi
  log "merge: $ad → $dst"
  "$PY" train/lines/_shared/scripts/local_merge_lora.py --base "$M/OxCoder-9B" --adapter "$ad" --out "$dst" >> "$LOG" 2>&1
  local rc=$?
  log "merge 退出 rc=$rc"
  # pin architectures（PLAN §6.1 的坑：不 pin 会走 VL 分支）
  "$PY" - "$dst" <<'PYEOF' >> "$LOG" 2>&1
import json, os, sys
d = sys.argv[1]
p = os.path.join(d, "config.json")
if os.path.exists(p):
    c = json.load(open(p, encoding="utf-8"))
    c["architectures"] = ["Qwen3_5ForConditionalGeneration"]
    json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[pin] {d} architectures={c['architectures']}")
else:
    print(f"[pin] 缺 {p}")
PYEOF
  return 0
}

merge_one "$OUT/z-re-v4/final"  "$M/merged-zre-v4"
merge_one "$OUT/z-2a-v7/final"  "$M/merged-z2a-v7"

log "=== 产物核对 ==="
for d in "$M/merged-zre-v4" "$M/merged-z2a-v7"; do
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  n=$(ls "$d"/*.safetensors 2>/dev/null | wc -l)
  arch=$("$PY" -c "import json;print(json.load(open('$d/config.json',encoding='utf-8')).get('architectures'))" 2>/dev/null)
  log "$d | 体积 ${sz:-NA} | 分片数 $n | architectures=$arch"
done

log "=== 冒烟（各 5 条，比对 adapter 与 merged）==="
# 显存闸门：合并只用 CPU/RAM，但冒烟要 4bit 载入模型
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 )); [ $((el % 300)) -lt 30 ] && log "显存 ${used}MiB 占用，等待 … ${el}s"
  [ "$el" -gt 900 ] && { log "超 15min → 停 ninfer 接管"; taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1; sleep 10; break; }
  sleep 30
done
"$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
  --adapters "zre_adapter=$OUT/z-re-v4/final,merged_re=$M/merged-zre-v4" \
  --cases 5 --max-new 300 --out "$OUT/smoke-re-merged.json" >> "$LOG" 2>&1
log "RE 冒烟 rc=$?"

"$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$M/merged-z2a-v7" --limit 5 --max-new 1200 \
  --out "$OUT/smoke-2a-merged.json" >> "$LOG" 2>&1
log "2A 冒烟(merged) rc=$?"

"$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v7/final" --limit 5 --max-new 1200 \
  --out "$OUT/smoke-2a-adapter.json" >> "$LOG" 2>&1
log "2A 冒烟(adapter) rc=$?"

log "=== 汇总 ==="
"$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
def j(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None
re_s = j("train/lines/9b-oxcoder/out/smoke-re-merged.json")
if re_s:
    for r in re_s.get("results", []):
        print(f"[RE] {r['label']}: hit {r['hit']}/{r['n']} fake {r['fake']} wrong {r['wrong']}")
a_m = j("train/lines/9b-oxcoder/out/smoke-2a-merged.json") or {}
a_a = j("train/lines/9b-oxcoder/out/smoke-2a-adapter.json") or {}
print(f"[2A] merged : cov {a_m.get('avg_cov')} code {a_m.get('code_rate')} n={a_m.get('n')}")
print(f"[2A] adapter: cov {a_a.get('avg_cov')} code {a_a.get('code_rate')} n={a_a.get('n')}")
if a_m.get("avg_cov") is not None and a_a.get("avg_cov") is not None:
    print(f"[判据] merged 与 adapter 的 cov 差 = {abs(a_m['avg_cov']-a_a['avg_cov']):.4f}（<0.10 视为等价）")
PYEOF
log "================ P3 结束 ================"
