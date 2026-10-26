#!/usr/bin/env bash
# fill3.sh —— 按已知目标尺寸，用 Range 续写剩余字节（不依赖服务端支持 -C -）
# 用法：fill3.sh 03 06 17
set -uo pipefail
BASE=https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main
DIR=/root/autodl-tmp/base-hf/Huihui
cd "$DIR" || exit 2

want_of() {
  case "$1" in
    03) echo 2542796928 ;;
    06) echo 3979553664 ;;
    13) echo 2108759312 ;;
    16) echo 3979564008 ;;
    17) echo 2108759312 ;;
  esac
}

fetch_one() {
  n="$1"; f="model-000$n-of-00018.safetensors"; want=$(want_of "$n")
  for attempt in 1 2 3 4 5 6 7 8; do
    have=$(stat -c%s "$f" 2>/dev/null || echo 0)
    if [ "$have" -eq "$want" ]; then echo "OK $f $have"; return 0; fi
    if [ "$have" -gt "$want" ]; then echo "OVER $f have=$have want=$want -> truncate"; truncate -s "$want" "$f"; have=$want; continue; fi
    echo "FETCH $f have=$have need=$((want-have)) attempt=$attempt"
    curl -fsSL -r "${have}-" --retry 3 --retry-all-errors --connect-timeout 10 --max-time 1800 \
         -o /tmp/part_$n "$BASE/$f" || { sleep 2; continue; }
    cat /tmp/part_$n >> "$f"; rm -f /tmp/part_$n
  done
  have=$(stat -c%s "$f" 2>/dev/null || echo 0)
  [ "$have" -eq "$want" ] && { echo "OK $f $have"; return 0; } || { echo "FAIL $f have=$have want=$want"; return 1; }
}

for n in "$@"; do fetch_one "$n" & done
wait
echo "=== 结果 ==="
for n in "$@"; do f="model-000$n-of-00018.safetensors"; printf "%s have=%s want=%s\n" "$f" "$(stat -c%s "$f" 2>/dev/null || echo 0)" "$(want_of "$n")"; done
