#!/usr/bin/env bash
# Z-B v6：修 v5 的两处负迁移（实测 zbv5 29/40 比 zbv4 30/40 退 1 条）
#
# 依据（eval-re-zbv5.json 逐条对比）：
#   变好 G17（ida vs ghidra）✓ 对比样本有效
#   变坏 G11 expect[kitty_net, kitty_proto] → 只给 kitty_net
#        原因：纪律样本写死「一次只给这一个调用」，把多步任务也压成单工具
#   变坏 G33 expect[kitty_asm] → 给纯文字回答没调工具
#        原因：58 工具正例拿 description 原文当问句，学成「介绍工具」而非「用工具」
#
# 处方 v6：
#   ① 纪律句全量改写（2244 条）：允许链式，每步带判据；禁止的是罗列备选
#   ② 正例问法改任务式（「用工具完成 X。给出调用。」）
#   ③ 新增 12 条多步链 × 3 问法 × 3 提权 = 144 条（L3 主形态）
#   ④ 保留 v5 的 318 条手写对比（G17 的功臣）
set -u
cd "$(dirname "$0")/../../.." || exit 1
PY=./train/.venv/Scripts/python.exe
L=train/logs
OUT=train/lines/9b-oxcoder/out
D9=train/lines/9b-oxcoder/data
DATA="$D9/_legacy/mix-z-re-v6-train.jsonl"
LOG="$L/zb-v6.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "================ Z-B v6 启动 pid=$$ ================"
[ -f "$DATA" ] || { log "缺数据：$DATA → 中止"; exit 1; }
log "数据 $(wc -l < "$DATA") 行"

# 显存闸门：等 2B v4 跑完（只清 ninfer，绝不杀训练）
# ── 单实例锁（pidfile 版：git-bash 没有 flock）──
LOCK="$L/.train.pid"
# 等待式：v6 是排队链，等到前一条链释放锁再跑（最多 14h）
t0=$(date +%s)
while [ -f "$LOCK" ]; do
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -z "$OLDPID" ] || [ "$OLDPID" = "0" ] || ! kill -0 "$OLDPID" 2>/dev/null; then
    log "旧锁残留 pid=$OLDPID 已死 → 清理"; rm -f "$LOCK"; break
  fi
  el=$(( $(date +%s) - t0 ))
  [ $((el % 600)) -lt 30 ] && log "等前一条训练 pid=$OLDPID 释放锁 … ${el}s"
  [ "$el" -gt 50400 ] && { log "等锁超 14h → 中止"; exit 3; }
  sleep 60
done
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
log "拿到训练锁 pid=$$"

log "等待显存 <1500MiB（最多 14h）"
t1=$(date +%s)
while :; do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' '); used=${used:-0}
  [ "$used" -lt 1500 ] && { log "显存空闲 ${used}MiB"; break; }
  el=$(( $(date +%s) - t1 ))
  [ $((el % 900)) -lt 30 ] && log "显存 ${used}MiB 占用 … 已等 ${el}s"
  [ "$el" -gt 50400 ] && { log "等待超 14h → 中止"; exit 1; }
  sleep 60
done

# 训练
if [ ! -d "$OUT/z-re-v6/final" ]; then
  STEPS=$(( $(wc -l < "$DATA") / 4 ))
  log "训练开始：init=r3 · ${STEPS} 步 · 1 epoch · lr 2e-5"
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
  PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B --data "$DATA" --stage re \
    --init-adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out "$OUT/z-re-v6" \
    --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 400 --save-total-limit 6 >> "$L/zb-v6-train.log" 2>&1
  log "训练退出 rc=$?"
else
  log "训练产物已存在，跳过"
fi

# 评测：四档对照（r3 / zbv4 / zbv5 / zbv6）
if [ -d "$OUT/z-re-v6/final" ]; then
  log "评测四档对照（各 40 条）"
  PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
  "$PY" -u train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "zbv4=$OUT/z-re-v4/final,zbv5=$OUT/z-re-v5/final,zbv6=$OUT/z-re-v6/final" \
    --max-new 300 --batch 1 --out "$OUT/eval-re-zbv6.json" >> "$L/zb-v6-eval.log" 2>&1
  log "评测 rc=$?"
fi

log "================ Z-B v6 结束 ================"
PYTHONIOENCODING=utf-8 "$PY" - <<'PYEOF' 2>&1 | tee -a "$LOG"
import json, os
p = "train/lines/9b-oxcoder/out/eval-re-zbv6.json"
if not os.path.exists(p):
    print("未产出评测结果"); raise SystemExit
d = json.load(open(p, encoding="utf-8"))
print(f"{'label':<8}{'hit':>5}{'acc':>8}{'wrong':>7}{'noarg':>7}{'fake':>6}  by_level")
for r in d["results"]:
    print(f"{r['label']:<8}{r['hit']:>5}{r['acc']:>8}{r['wrong']:>7}"
          f"{r['noarg']:>7}{r['fake']:>6}  {r['by_level']}")
PYEOF
