#!/usr/bin/env bash
# 方案 Z · 剩余流程总接管（幂等 / 可续跑 / 每步落盘）
#   STEP0 等 Z-B 训练退出（不改已在跑的进程）
#   STEP1 选 ZRE adapter（final 优先，缺则取最新 checkpoint）
#   STEP2 RE 评测（r3 对照 + zre，40 题）
#   STEP3 Z-2A v2 训练（3 epoch = 864 步，补 cov）
#   STEP4 Z-2A v2 评测（final 不足则补评中间 ckpt，取优）
#   STEP5 三门禁（eval / toolname / notool）
#   STEP6 汇总报告 z-final-report.md
# 幂等：每步成功写 train/logs/.takeover/stepN.done，重跑自动跳过
set -u
cd "$(dirname "$0")/../.." || exit 1

PY=./train/.venv/Scripts/python.exe
L=train/logs
OUT=train/lines/9b-oxcoder/out
TK="$L/takeover-z.log"
MK="$L/.takeover"
STAGES="$L/z-stages.md"
ZRE_WAIT_MAX=${ZRE_WAIT_MAX:-7200}

mkdir -p "$MK" "$L"
log()   { echo "[$(date '+%F %T')] $*" >> "$TK"; }
stamp() { echo "| $(date '+%F %T') | $1 |" >> "$STAGES"; }
done_() { [ -f "$MK/$1.done" ]; }
mark()  { echo "ok $(date '+%F %T')" > "$MK/$1.done"; }

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export VRAM_FRAC=0.93 PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1
export OMP_NUM_THREADS=6 MKL_NUM_THREADS=6

log "================ 接管启动 pid=$$ ================"
[ -f "$STAGES" ] || { echo "| 时间 | 阶段 |" >> "$STAGES"; echo "|---|---|" >> "$STAGES"; }

# ---------- 进度采样器（后台，60s 一次） ----------
"$PY" -u train/lines/_shared/scripts/z_progress.py >> "$L/z-progress.err" 2>&1 &
PROG_PID=$!
trap 'kill $PROG_PID 2>/dev/null' EXIT

# ---------- STEP0：等 Z-B 训练退出 ----------
if ! done_ step0; then
  log "STEP0 等待 Z-B 训练进程退出（上限 ${ZRE_WAIT_MAX}s）"
  t0=$(date +%s)
  while ps -ef | grep -q "[t]rain_qlora9b.py.*mix-z-re.jsonl"; do
    sleep 30
    el=$(( $(date +%s) - t0 ))
    [ $((el % 300)) -lt 30 ] && log "STEP0 等待中 ${el}s"
    if [ "$el" -gt "$ZRE_WAIT_MAX" ]; then log "STEP0 超时 ${el}s → 按现有 checkpoint 继续"; break; fi
  done
  mark step0; stamp "STEP0 完成 · Z-B 训练进程已退出"
  log "STEP0 完成"
fi

# ---------- STEP1：选 ZRE adapter ----------
ZRE=""
if [ -d "$OUT/z-re/final" ]; then
  ZRE="$OUT/z-re/final"
else
  ZRE=$(ls -d "$OUT"/z-re/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
fi
log "STEP1 ZRE adapter = ${ZRE:-<缺失>}"

# ---------- STEP2：RE 评测 ----------
if ! done_ step2; then
  if [ -n "${ZRE:-}" ] && [ -d "$ZRE" ]; then
    log "STEP2 RE 评测开始（r3 对照 + zre）"
    stamp "STEP2 开始 · RE 评测（40 题 × 2 adapter）"
    "$PY" train/lines/_shared/scripts/eval_multi_adapter.py \
      --adapters "r3=$OUT/re-stage1-r3/final,zre=$ZRE" \
      --max-new 300 --batch 1 --out "$OUT/eval-re-zre.json" >> "$TK" 2>&1
    rc=$?
    if [ $rc -eq 0 ] && [ -f "$OUT/eval-re-zre.json" ]; then
      mark step2; stamp "STEP2 完成 · eval-re-zre.json"; log "STEP2 OK"
    else
      log "STEP2 失败 rc=$rc（继续后续步骤）"
    fi
  else
    log "STEP2 跳过：无 ZRE adapter"; mark step2
  fi
fi

# ---------- STEP3：Z-2A v2 训练（3 epoch） ----------
if [ ! -d "$OUT/z-2a-v2/final" ]; then
  log "STEP3 Z-2A v2 训练开始（3 epoch / 864 步 / 数据 mix-z-2a.jsonl）"
  stamp "STEP3 开始 · Z-2A v2 训练（864 步）"
  "$PY" -u train/lines/_shared/scripts/train_qlora9b.py \
    --base train/lines/9b-oxcoder/models/OxCoder-9B \
    --data train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl \
    --stage re --out "$OUT/z-2a-v2" \
    --ctx 2048 --epochs 3 --lr 3e-5 --ga 4 --bs 1 \
    --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
    --save-steps 200 --save-total-limit 6 >> "$L/z-2a-v2-train.log" 2>&1
  log "STEP3 训练进程退出 rc=$?"
  [ -d "$OUT/z-2a-v2/final" ] && stamp "STEP3 完成 · z-2a-v2/final" || stamp "STEP3 结束 · final 缺失"
else
  log "STEP3 跳过：z-2a-v2/final 已存在"; stamp "STEP3 跳过 · 已有 final"
fi

# ---------- STEP4：Z-2A v2 评测（不足则补评中间 ckpt） ----------
if ! done_ step4 && [ -d "$OUT/z-2a-v2/final" ]; then
  log "STEP4 Z-2A v2 评测开始（final）"
  stamp "STEP4 开始 · Z-2A v2 评测"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$OUT/z-2a-v2/final" \
    --max-new 1200 --out "$OUT/eval-2a-z2a-v2.json" >> "$TK" 2>&1
  cov=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v2.json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
  log "STEP4 final cov=$cov"
  # final 欠训（cov<0.55）→ 补评中间 ckpt，取 cov 最高者另存
  if "$PY" -c "import sys;sys.exit(0 if float('$cov')<0.55 else 1)" 2>/dev/null; then
    best=""; bestcov="$cov"
    for ck in $(ls -d "$OUT"/z-2a-v2/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -3); do
      log "STEP4 补评 $ck"
      "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$ck" \
        --max-new 1200 --out "$OUT/eval-2a-z2a-v2-$(basename "$ck").json" >> "$TK" 2>&1
      c=$("$PY" -c "import json;print(json.load(open('$OUT/eval-2a-z2a-v2-$(basename "$ck").json',encoding='utf-8'))['avg_cov'])" 2>/dev/null || echo 0)
      log "  $ck cov=$c"
      if "$PY" -c "import sys;sys.exit(0 if float('$c')>float('$bestcov') else 1)" 2>/dev/null; then
        best="$ck"; bestcov="$c"
      fi
    done
    if [ -n "$best" ]; then
      cp "$OUT/eval-2a-z2a-v2-$(basename "$best").json" "$OUT/eval-2a-z2a-v2.json"
      log "STEP4 取优：$best cov=$bestcov 覆盖主结果"
      stamp "STEP4 补评取优 · $(basename "$best") cov=$bestcov"
    fi
  fi
  mark step4; stamp "STEP4 完成 · eval-2a-z2a-v2.json"
fi

# ---------- STEP5：三门禁 ----------
if ! done_ step5; then
  log "STEP5 门禁开始"
  if [ -f "$OUT/eval-2a-z2a-v2.json" ]; then
    { echo "=== eval gate $(date '+%F %T') ==="; \
      "$PY" train/lines/_shared/scripts/check_eval_gate.py "$OUT/eval-2a-z2a-v2.json" --base "$OUT/eval-2a-r3-v2.json"; \
      echo "rc=$?"; } >> "$L/gate-z2a-v2.log" 2>&1
  fi
  { echo "=== toolname gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_toolname_gate.py train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl; echo "rc=$?"; } \
    >> "$L/gate-toolname-z2a.log" 2>&1
  { echo "=== notool gate $(date '+%F %T') ==="; \
    "$PY" train/lines/_shared/scripts/check_notool_gate.py train/lines/9b-oxcoder/data/_legacy/mix-z-2a.jsonl; echo "rc=$?"; } \
    >> "$L/gate-notool-z2a.log" 2>&1
  mark step5; stamp "STEP5 完成 · 三门禁（见 gate-*.log）"; log "STEP5 OK"
fi

# ---------- STEP6：汇总 ----------
if ! done_ step6; then
  log "STEP6 汇总报告"
  "$PY" train/lines/_shared/scripts/aggregate_z.py >> "$TK" 2>&1
  rc=$?
  [ $rc -eq 0 ] && { mark step6; stamp "STEP6 完成 · train/logs/z-final-report.md"; log "STEP6 OK"; } \
                || log "STEP6 失败 rc=$rc"
fi

log "================ 接管结束 $(date '+%F %T') ================"
stamp "ALL DONE · 接管流程结束"
