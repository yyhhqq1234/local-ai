#!/usr/bin/env bash
# watch_free.sh —— 按门进度释放磁盘：G2 PASS 删基座分片；G3 PASS 删 merged 分片
R=/root/autodl-tmp/kitty-rev
L=$R/logs/v4/REBUILD.log
B=/root/autodl-tmp/base-hf/Huihui
M=/root/autodl-tmp/merged-v4
F=$R/logs/v4/.freed
mkdir -p "$(dirname "$F")"
for i in $(seq 1 240); do
  if ! grep -q '^G2' "$F" 2>/dev/null && grep -q '\[G2\] PASS' "$L" 2>/dev/null; then
    n=$(ls "$B"/*.safetensors 2>/dev/null | wc -l)
    rm -f "$B"/*.safetensors
    echo "G2" >> "$F"
    echo "[$(date +%H:%M:%S)] freed base shards n=$n free=$(df -h /root/autodl-tmp|awk 'NR==2{print $4}')" >> "$R/logs/v4/FREE.log"
  fi
  if ! grep -q '^G3' "$F" 2>/dev/null && grep -q '\[G3\] PASS' "$L" 2>/dev/null; then
    n=$(ls "$M"/*.safetensors 2>/dev/null | wc -l)
    rm -f "$M"/*.safetensors
    echo "G3" >> "$F"
    echo "[$(date +%H:%M:%S)] freed merged shards n=$n free=$(df -h /root/autodl-tmp|awk 'NR==2{print $4}')" >> "$R/logs/v4/FREE.log"
  fi
  sleep 5
done
