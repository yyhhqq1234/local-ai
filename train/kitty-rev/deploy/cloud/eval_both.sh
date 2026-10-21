#!/usr/bin/env bash
# eval_both.sh -- serial base-vs-adapter evaluation on one GPU, one code path.
#
#   stage 1: serve(base)                -> eval_kitty -> logs/eval-base-repro.json
#   stage 2: serve(base + out/adapter)  -> eval_kitty -> logs/eval-adapter.json
#
# Strictly serial: stage 2 starts only after stage 1's serve PID is dead.
# Kill is by exact PID ($!), never pkill by pattern.
# Refuses to start if the GPU is already owned by another process (full training).
#
# Run only after train-watch reports the 3-epoch full run finished.
set -u
ROOT=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
SERVE=$ROOT/scripts/serve_4bit_base.py
BASE=$ROOT/base/Qwen3.8-27B
ADAPTER=$ROOT/out/adapter
PORT=${PORT:-18000}
LOGD=$ROOT/logs
EVALD=$ROOT/kitty-rev/logs
DATA=$ROOT/kitty-rev/data/eval.jsonl
EVAL=$ROOT/kitty-rev/eval/eval_kitty.py
mkdir -p "$LOGD" "$EVALD"

echo "=== eval_both $(date '+%F %T') ==="
for f in "$SERVE" "$DATA" "$EVAL" "$BASE/config.json"; do
  [ -e "$f" ] || { echo "[FATAL] missing $f"; exit 2; }
done
[ -d "$ADAPTER" ] || echo "[WARN] adapter dir missing: $ADAPTER"

gate() {
  local apps used
  apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc '0-9')
  echo "[gate] apps=$apps vram=${used:-?}MiB"
  if [ "${apps:-9}" != "0" ] || [ "${used:-9999}" -gt 3000 ]; then
    echo "[gate] REFUSE: GPU busy -- another process owns it (training?)"
    return 3
  fi
  return 0
}

wait_ready() {
  local pid=$1 i
  for i in $(seq 1 90); do
    if curl -s --max-time 3 "http://127.0.0.1:$PORT/v1/models" > /dev/null 2>&1; then
      return 0
    fi
    kill -0 "$pid" 2>/dev/null || return 4
    sleep 5
  done
  return 5
}

run_one() {
  local tag=$1; shift
  local sm=$LOGD/serve-$tag.log
  local ev=$LOGD/eval-$tag.log
  local out=$EVALD/eval-$tag.json
  local peak=$LOGD/peak-$tag.txt

  echo "=== [$tag] start $(date '+%F %T') ==="
  gate || return 3

  "$PY" -u "$SERVE" "$@" --port "$PORT" > "$sm" 2>&1 &
  local pid=$!
  echo "[$tag] serve_pid=$pid"
  if ! wait_ready "$pid"; then
    echo "[$tag] SERVE_FAIL rc=$?"; tail -30 "$sm"; kill "$pid" 2>/dev/null; return 1
  fi
  echo "[$tag] ready: $(curl -s "http://127.0.0.1:$PORT/v1/models")"

  echo 0 > "$peak"
  ( p=0
    while kill -0 "$pid" 2>/dev/null; do
      v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc '0-9')
      if [ -n "$v" ] && [ "$v" -gt "$p" ]; then p=$v; echo "$p" > "$peak"; fi
      sleep 2
    done ) &
  local samp=$!

  local t0 t1 rc
  t0=$(date +%s)
  "$PY" -u "$EVAL" --base "http://127.0.0.1:$PORT" --model "$tag" \
        --data "$DATA" --out "$out" --verbose > "$ev" 2>&1
  rc=$?
  t1=$(date +%s)
  echo "[$tag] eval_rc=$rc elapsed=$((t1 - t0))s peak_vram=$(cat "$peak" 2>/dev/null)MiB"
  grep -a '总通过' "$ev" | head -2
  grep -aE '^  (tool-route|op-syntax|real-trajectory|error-recovery|transition-syntax)' "$ev" | head -8

  kill "$samp" 2>/dev/null
  kill "$pid" 2>/dev/null
  sleep 4
  if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; sleep 2; fi
  echo "[$tag] serve stopped (pid $pid)"
  return 0
}

run_one base --model "$BASE"
run_one adapter --model "$BASE" --adapter "$ADAPTER"

echo "=== summary $(date '+%F %T') ==="
for t in base adapter; do
  j=$EVALD/eval-$t.json
  if [ -f "$j" ]; then
    echo "[$t] $(grep -a '"pass"' "$j" | head -1) $(grep -a '"total"' "$j" | head -1)"
  else
    echo "[$t] MISSING $j"
  fi
done
echo "=== DONE $(date '+%F %T') ==="
