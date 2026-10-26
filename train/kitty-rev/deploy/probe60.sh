#!/bin/bash
# probe60.sh - 8-way concurrent, 60s REAL disk-write throughput (gate for switching source).
# Writes only into /root/autodl-tmp/kitty-rev/_spdtest and deletes it afterwards.
# Never touches PID 1312/1363 or shard01.
set -u
REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
BASE="https://hf-mirror.com/$REPO/resolve/main"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
DIR=/root/autodl-tmp/kitty-rev/_spdtest
DUR=${1:-60}

rm -rf "$DIR"; mkdir -p "$DIR"; cd "$DIR" || exit 1
echo "=== probe60 START $(date '+%F %T')  dur=${DUR}s  8 files -> $DIR ==="

t0=$(date +%s)
for i in 02 03 04 05 06 07 08 09; do
  f="model-000${i}-of-00018.safetensors"
  ( curl -sS -L --max-time "$DUR" -o "$f" -H "User-Agent: $UA" "$BASE/$f" \
      > "$f.err" 2>&1 ) &
done
wait
t1=$(date +%s)
dt=$(( t1 - t0 ))
[ "$dt" -lt 1 ] && dt=1

echo "--- per-file bytes ---"
for i in 02 03 04 05 06 07 08 09; do
  f="model-000${i}-of-00018.safetensors"
  sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
  printf "  %-38s %12s B  %6.2f MiB/s\n" "$f" "$sz" \
    "$(awk -v s="$sz" -v d="$dt" 'BEGIN{printf "%.2f", s/1048576/d}')"
done

tot=$(du -cb *.safetensors 2>/dev/null | tail -1 | cut -f1)
echo "--- TOTAL ---"
echo "  bytes=${tot:-0}  wall=${dt}s"
awk -v s="${tot:-0}" -v d="$dt" 'BEGIN{
  mbps = s/1048576/d;
  printf "  aggregate = %.2f MiB/s\n", mbps;
  printf "  GATE(>=3 MiB/s for 60s) : %s\n", (mbps>=3.0 ? "PASS" : "FAIL");
  rem = 73800000000 - 2450000000;
  printf "  ETA for remaining %.1f GB at this rate = %.2f h\n", rem/1e9, rem/1048576/mbps/3600;
}'
cd / ; rm -rf "$DIR"
echo "=== probe60 END $(date '+%F %T') ==="
