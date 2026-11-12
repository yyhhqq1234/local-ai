#!/bin/bash
# 云端补片：按「分片号:字节数」补下缺失分片（低并发 + 退避重试，避开 hf-mirror 429）
# 用法: bash dl_shards.sh 14:3979553696 15:2108759344 ...
source /etc/network_turbo 2>/dev/null
DST=/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B
BASEURL=https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main
mkdir -p "$DST"
for arg in "$@"; do
  n=${arg%%:*}
  want=${arg##*:}
  f=$(printf "model-%05d-of-00018.safetensors" "$n")
  out="$DST/$f"
  have=$(stat -c %s "$out" 2>/dev/null || echo 0)
  if [ "$have" = "$want" ]; then echo "[$f] 已完整 $want"; continue; fi
  echo "[$f] 现有 ${have}B / 目标 ${want}B → 续传"
  for try in 1 2 3 4 5 6 7 8 9 10; do
    curl -sSL -C - --retry 5 --retry-delay 10 --retry-all-errors \
         --connect-timeout 30 --max-time 2400 -o "$out" "$BASEURL/$f"
    have=$(stat -c %s "$out" 2>/dev/null || echo 0)
    [ "$have" = "$want" ] && break
    echo "[$f] 第 $try 轮后 ${have}/${want}，等 8s 重试"
    sleep 8
  done
  have=$(stat -c %s "$out" 2>/dev/null || echo 0)
  echo "[$f] 结束 ${have}/${want} $([ "$have" = "$want" ] && echo OK || echo INCOMPLETE)"
done
echo "=== dl_shards 全部结束 $(date +%H:%M:%S) ==="
