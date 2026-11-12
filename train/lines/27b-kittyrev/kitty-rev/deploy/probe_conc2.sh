#!/bin/bash
# probe_conc2.sh - find the concurrency CEILING (T8 / T12) on hf-mirror. READ-ONLY.
set -u
REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE="https://hf-mirror.com/$REPO/resolve/main"
CAP=30
RANGE="0-33554431"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
MB=1048576
SHARD1=/root/autodl-tmp/kitty-rev/base/Huihui/model-00001-of-00018.safetensors

one() {
  curl -sS -L --max-time "$CAP" -r "$RANGE" -o /dev/null -H "User-Agent: $UA" \
       -w "%{speed_download} %{http_code} %{size_download}" "$BASE/$1" 2>/dev/null
}
mbs() { awk -v t="${1:-0}" -v m="$MB" 'BEGIN{printf "%.2f", t/m}'; }

run_n() {   # $1 = N, fills TOT
  local N=$1 i=0 pids="" tot=0 f sp code nb
  rm -f /tmp/pn_*.out
  for i in $(seq 2 $((N+1))); do
    f=$(printf "model-%05d-of-00018.safetensors" "$i")
    ( one "$f" > /tmp/pn_$i.out 2>&1 ) & pids="$pids $!"
  done
  wait $pids
  i=0
  for j in $(seq 2 $((N+1))); do
    read -r sp code nb < /tmp/pn_$j.out
    i=$((i+1))
    printf "   f%02d %6.2f MiB/s http=%s\n" "$i" "$(mbs "${sp:-0}")" "${code:-NA}"
    tot=$(awk -v a=$tot -v b="${sp:-0}" 'BEGIN{printf "%.0f", a+b}')
  done
  echo "   N=$N TOTAL = $(mbs "$tot") MiB/s"
  TOT=$tot
}

n0=$(stat -c %s "$SHARD1" 2>/dev/null || echo 0); t00=$(date +%s)
echo "############ probe_conc2 START $(date '+%F %T') ############"
echo "live shard01 start = $n0 B"

echo
echo "=== [T8] 8 files concurrent (shard02..09) ==="
run_n 8; T8=$TOT
n8=$(stat -c %s "$SHARD1" 2>/dev/null || echo 0); t8=$(date +%s)

echo
echo "=== [T12] 12 files concurrent (shard02..13) ==="
run_n 12; T12=$TOT
n12=$(stat -c %s "$SHARD1" 2>/dev/null || echo 0); t12=$(date +%s)

echo
echo "=== [Z] CEILING ==="
echo "  T1  (serial, earlier) = 3.07 MiB/s   [replan baseline from probe_conc]"
echo "  T4  (earlier)         = 6.97 MiB/s"
echo "  T8  = $(mbs "$T8") MiB/s"
echo "  T12 = $(mbs "$T12") MiB/s"
echo "  shard01 grew during T8  : $(( n8 - n0 )) B in $(( t8 - t00 ))s"
echo "  shard01 grew during T12 : $(( n12 - n8 )) B in $(( t12 - t8 ))s"
echo "  => total-link estimate at T8  = $(mbs $(( T8 + (n8-n0)*MB/((t8-t00>0)?(t8-t00):1) ))) MiB/s"
echo "  => total-link estimate at T12 = $(mbs $(( T12 + (n12-n8)*MB/((t12-t8>0)?(t12-t8):1) ))) MiB/s"
echo "############ END $(date '+%F %T') ############"
