#!/bin/bash
# probe_conc.sh - DIFFERENT-FILE concurrency test (READ-ONLY; never touches shard 01)
# Answers: is hf-mirror limited per-URL (concurrency helps) or globally (does not)?
set -u
REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE="https://hf-mirror.com/$REPO/resolve/main"
CAP=30
RANGE="0-33554431"   # 32 MiB
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
MB=1048576
SHARD1=/root/autodl-tmp/kitty-rev/base/Huihui/model-00001-of-00018.safetensors

one() {
  curl -sS -L --max-time "$CAP" -r "$RANGE" -o /dev/null -H "User-Agent: $UA" \
       -w "%{speed_download} %{http_code} %{size_download} %{time_total}" "$BASE/$1" 2>/dev/null
}
mbs() { awk -v t="${1:-0}" -v m="$MB" 'BEGIN{printf "%.2f", t/m}'; }

echo "############ probe_conc START $(date '+%F %T') ############"

n0=$(stat -c %s "$SHARD1" 2>/dev/null || echo 0); t00=$(date +%s)
echo "=== [T0] live shard01 = $n0 B  (PID 1312/1363 untouched) ==="
ps -eo pid,etime,cmd | grep '[c]url -C' || echo "  (no curl -C seen)"

echo
echo "=== [T1] SINGLE file serial : shard02 32MiB cap=${CAP}s ==="
r=$(one model-00002-of-00018.safetensors); read -r s1 c1 b1 t1 <<< "$r"
echo "  raw=[$r]"
echo "  T1 = $(mbs "$s1") MiB/s  http=$c1 got=$b1 B wall=${t1}s"
S1=$s1

echo
echo "=== [T4] FOUR different files CONCURRENT : shard02..05 ==="
rm -f /tmp/pc_*.out; i=0; pids=""
for f in model-00002-of-00018.safetensors model-00003-of-00018.safetensors \
         model-00004-of-00018.safetensors model-00005-of-00018.safetensors; do
  i=$((i+1)); ( one "$f" > /tmp/pc_$i.out 2>&1 ) & pids="$pids $!"
done
wait $pids
TOT4=0
for j in 1 2 3 4; do
  read -r sp code nb sec < /tmp/pc_$j.out
  echo "  file$j: $(mbs "${sp:-0}") MiB/s  http=${code:-NA}  got=${nb:-0} B  wall=${sec:-0}s"
  TOT4=$(awk -v a=$TOT4 -v b="${sp:-0}" 'BEGIN{printf "%.0f", a+b}')
done
RATIO4=$(awk -v a=$TOT4 -v b="${S1:-0}" 'BEGIN{printf "%.2f", (b>0)?a/b:0}')
echo "  T4 TOTAL = $(mbs "$TOT4") MiB/s   ratio_vs_T1 = ${RATIO4}x"

if awk -v r="$RATIO4" 'BEGIN{exit !(r>=2.5)}'; then
  echo
  echo "=== [T8] EIGHT different files CONCURRENT : shard02..09 ==="
  rm -f /tmp/p8_*.out; i=0; pids=""
  for f in model-00002-of-00018.safetensors model-00003-of-00018.safetensors \
           model-00004-of-00018.safetensors model-00005-of-00018.safetensors \
           model-00006-of-00018.safetensors model-00007-of-00018.safetensors \
           model-00008-of-00018.safetensors model-00009-of-00018.safetensors; do
    i=$((i+1)); ( one "$f" > /tmp/p8_$i.out 2>&1 ) & pids="$pids $!"
  done
  wait $pids
  TOT8=0
  for j in 1 2 3 4 5 6 7 8; do
    read -r sp code nb sec < /tmp/p8_$j.out
    echo "  file$j: $(mbs "${sp:-0}") MiB/s  http=${code:-NA}  got=${nb:-0} B"
    TOT8=$(awk -v a=$TOT8 -v b="${sp:-0}" 'BEGIN{printf "%.0f", a+b}')
  done
  echo "  T8 TOTAL = $(mbs "$TOT8") MiB/s   ratio_vs_T1 = $(awk -v a=$TOT8 -v b="${S1:-0}" 'BEGIN{printf "%.2f",(b>0)?a/b:0}')x"
else
  echo
  echo "=== [T8] SKIPPED (T4 ratio ${RATIO4}x < 2.5 => concurrency ineffective) ==="
  TOT8=0
fi

n1=$(stat -c %s "$SHARD1" 2>/dev/null || echo 0); t11=$(date +%s)
dt=$(( t11 - t00 ))
echo
echo "=== [Z] SUMMARY ==="
echo "  T1 single      = $(mbs "$S1") MiB/s"
echo "  T4 concurrent  = $(mbs "$TOT4") MiB/s  (${RATIO4}x)"
echo "  T8 concurrent  = $(mbs "${TOT8:-0}") MiB/s  ($(awk -v a=${TOT8:-0} -v b="${S1:-0}" 'BEGIN{printf "%.2f",(b>0)?a/b:0}')x)"
echo "  live shard01 grew $(( n1 - n0 )) B in ${dt}s => $(mbs $(awk -v d=$((n1-n0)) -v t=$dt 'BEGIN{printf "%.0f", (t>0)?d/t:0}')) MiB/s (competing with probe)"
echo "############ probe_conc END $(date '+%F %T') ############"
