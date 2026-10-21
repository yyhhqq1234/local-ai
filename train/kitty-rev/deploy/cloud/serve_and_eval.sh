#!/usr/bin/env bash
# serve_and_eval.sh -- start the 4bit base endpoint, reproduce the 23-question
# baseline, sample peak VRAM, then shut the endpoint down. Run on the AutoDL box
# only after the GPU is free (gate below enforces it).
set -u
ROOT=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
SLOG=$ROOT/logs/serve-4bit-base.log
ELOG=$ROOT/logs/eval-base-repro.log
OUT=$ROOT/kitty-rev/logs/eval-base-repro.json
PEAK=$ROOT/logs/vram-peak.txt
mkdir -p "$ROOT/logs"

apps=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l)
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc '0-9')
echo "GATE apps=$apps vram=${used}MiB"
if [ "${apps:-9}" != "0" ] || [ "${used:-9999}" -gt 3000 ]; then
  echo "GATE_FAIL gpu busy -- refusing to start serve"
  exit 3
fi

cd "$ROOT" || exit 1
rm -f "$PEAK"
echo 0 > "$PEAK"
nohup $PY -u scripts/serve_4bit_base.py > "$SLOG" 2>&1 &
SRV=$!
echo "SERVE_PID=$SRV"

ready=0
for i in $(seq 1 120); do
  if curl -s --max-time 3 http://127.0.0.1:18000/v1/models > /dev/null 2>&1; then
    echo "READY after ~$((i * 5))s"; ready=1; break
  fi
  if ! kill -0 "$SRV" 2>/dev/null; then
    echo "SERVE_DIED"; tail -40 "$SLOG"; exit 4
  fi
  sleep 5
done
[ "$ready" = "1" ] || { echo "SERVE_TIMEOUT"; tail -40 "$SLOG"; kill "$SRV" 2>/dev/null; exit 5; }

echo "--- /v1/models ---"; curl -s http://127.0.0.1:18000/v1/models; echo
echo "--- smoke request ---"
curl -s --max-time 180 http://127.0.0.1:18000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"base-qwen3.8-27b","messages":[{"role":"user","content":"回一个字：好"}],"max_tokens":16}'
echo

# peak VRAM sampler
( peak=0
  while kill -0 "$SRV" 2>/dev/null; do
    v=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | tr -dc '0-9')
    if [ -n "$v" ] && [ "$v" -gt "$peak" ]; then peak=$v; echo "$peak" > "$PEAK"; fi
    sleep 2
  done ) &
SAMP=$!

T0=$(date +%s)
$PY -u kitty-rev/eval/eval_kitty.py \
  --base http://127.0.0.1:18000 --model base-qwen3.8-27b \
  --out "$OUT" --verbose > "$ELOG" 2>&1
RC=$?
T1=$(date +%s)
echo "EVAL_RC=$RC ELAPSED=$((T1 - T0))s"

echo "--- eval tail ---"
tail -45 "$ELOG"
echo "PEAK_VRAM_MiB=$(cat "$PEAK" 2>/dev/null)"

kill "$SAMP" 2>/dev/null
kill "$SRV" 2>/dev/null
sleep 3
echo "SERVE_STOPPED"
echo "DONE"
