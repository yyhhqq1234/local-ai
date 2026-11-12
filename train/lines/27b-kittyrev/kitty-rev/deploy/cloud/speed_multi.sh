#!/bin/bash
# 云端多连接下载测速：n 路并发各拉一段，测聚合带宽
source /etc/network_turbo 2>/dev/null
N=${1:-8}
PIECE=${2:-6291456}
URL="https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main/model-00013-of-00018.safetensors"
cd /tmp && rm -f sp_*.bin
S=$(date +%s%N)
for i in $(seq 0 $((N-1))); do
  s=$((i*PIECE)); e=$((s+PIECE-1))
  curl -sSL -r $s-$e -o sp_$i.bin "$URL" &
done
wait
E=$(date +%s%N)
ms=$(( (E-S)/1000000 ))
bytes=$(du -cb sp_*.bin | tail -1 | cut -f1)
rm -f sp_*.bin
awk -v ms="$ms" -v b="$bytes" -v n="$N" 'BEGIN{printf "%.1f MB in %.1fs -> %.2f MB/s (%d 路)\n", b/1048576, ms/1000, b/1048576/(ms/1000), n}'
