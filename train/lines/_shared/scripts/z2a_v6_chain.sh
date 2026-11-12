#!/usr/bin/env bash
# Z-2A v6（路线 A）：改用真实 2A 语料 —— traj-all-capped（15909 行，OpenHands 形态，p50 2478 字符）
#   诊断依据：
#     · eval_2a_code 的 avg_cov = 任务标识符（文件名/函数名/错误码）在回答里的出现率
#     · v1/v2/v3/v5 用的都是 traj-2a-lite（≤900 字符截断版）或 kitty 长答 —— 都不是原生 2A 语料
#     · r3 的 cov 59.96% 正是由这批原生语料贡献，只是当时以混合形式喂入
#   做法：全量 1 epoch，system 统一替换为 SYSTEM_2A（与评测一致），剔除 34 行含工具名的脏行
set -u
cd "$(dirname "$0")/../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs; OUT=train/lines/9b-oxcoder/out
LOG="$L/z2a-v6.log"
log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
log "================ Z-2A v6 启动 pid=$$ ================"

# 等 GPU（进程 + 显存双条件）
t0=$(date +%s)
while ps -ef | grep -qE "[e]val_2a|[t]rain_qlora9b"; do
  sleep 30; el=$(( $(date +%s) - t0 ))
  [ $((el % 300)) -lt 30 ] && log "等待进程退出 … ${el}s"
  [ "$el" -gt 7200 ] && { log "超时强开"; break; }
done
# 显存：其他线路（27B 引擎 / nsfw 评测）占用时先等，15 min 后接管
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
  used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 ))
  [ $((el % 300)) -lt 30 ] && log "显存占用 ${used}MiB，等待 … ${el}s"
  if [ "$el" -gt 900 ]; then
    log "显存被占 ${used}MiB 超 15min → 停 ninfer 引擎接管显卡"
    taskkill //IM ninfer-serve.exe //F >> "$LOG" 2>&1
    sleep 10; break
  fi
  sleep 30
done
log "GPU 就绪"

DATA=train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v6.jsonl
if [ ! -f "$DATA" ]; then
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, re, sys
sys.path.insert(0, "train/lines/_shared/scripts")
from sys_prompts import SYSTEM_2A
src = "train/lines/9b-oxcoder/data/agent-traj/traj-all-capped.jsonl"
out, drop = [], 0
pat = re.compile(r"kitty_|reverse_submit|<tool_call")
for l in open(src, encoding="utf-8"):
    o = json.loads(l); msgs = o.get("messages") or []
    a = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant")
    if pat.search(a):
        drop += 1; continue
    new = []
    for m in msgs:
        if m.get("role") == "system":
            new.append({"role": "system", "content": SYSTEM_2A})
        else:
            new.append(m)
    if not any(m.get("role") == "system" for m in new):
        new = [{"role": "system", "content": SYSTEM_2A}] + new
    out.append({"messages": new})  # 不带 meta：各源 meta 结构不一，会触发 datasets 的 cast 错误
with open("train/lines/9b-oxcoder/data/_legacy/mix-z-2a-v6.jsonl", "w", encoding="utf-8") as f:
    for r in out: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"[build] 源 15909 行 · 剔除含工具名 {drop} 行 · 输出 {len(out)} 行 · system=SYSTEM_2A")
PYEOF
  log "数据已建：$DATA"
else
  log "数据已存在：$DATA"
fi

{ echo "=== notool gate $(date '+%F %T') ==="; "$PY" train/lines/_shared/scripts/check_notool_gate.py "$DATA"; echo "rc=$?"; } \
  >> "$L/gate-notool-z2a-v6.log" 2>&1
{ echo "=== toolname gate $(date '+%F %T') ==="; "$PY" train/lines/_shared/scripts/check_toolname_gate.py "$DATA"; echo "rc=$?"; } \
  >> "$L/gate-toolname-z2a-v6.log" 2>&1
log "两门禁已跑"

if [ ! -d "$OUT/z-2a-v6/final" ]; then
  log "训练开始：$(wc -l < "$DATA") 行 · 1 epoch · lr 3e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re --out "$OUT/z-2a-v6" \
    --ctx 2048 --epochs 1 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 400 --save-total-limit 6 >> "$L/z-2a-v6-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "跳过训练"
fi

if [ -d "$OUT/z-2a-v6/final" ]; then
  best="$OUT/eval-2a-z2a-v6-final.json"
  log "评测：final"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v6/final" --max-new 1200 --out "$best" >> "$LOG" 2>&1
  bestcov=$("$PY" -c "import json;print(json.load(open('$best',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "final cov=$bestcov"
  for ck in $(ls -dv "$OUT"/z-2a-v6/checkpoint-* 2>/dev/null | tail -3); do
    nm=$(basename "$ck")
    log "评测：$nm"
    "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" --max-new 1200 --out "$OUT/eval-2a-z2a-v6-$nm.json" >> "$LOG" 2>&1
    c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v6-$nm.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
    log "  $nm cov=$c"
    if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
      best="$OUT/eval-2a-z2a-v6-$nm.json"; bestcov="$c"
    fi
  done
  cp "$best" "$OUT/eval-2a-z2a-v6.json"
  log "取优：$best cov=$bestcov"
  { echo "=== eval gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v6.json" --base "$OUT/eval-2a-r3-v2.json"; echo "rc=$?"; } \
    >> "$L/gate-z2a-v6.log" 2>&1
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$LOG" 2>&1
  log "汇总完成 rc=$?"
  echo "| $(date '+%F %T') | Z-2A v6 完成 · cov=$bestcov |" >> "$L/z-stages.md"
fi
log "================ Z-2A v6 结束 ================"
