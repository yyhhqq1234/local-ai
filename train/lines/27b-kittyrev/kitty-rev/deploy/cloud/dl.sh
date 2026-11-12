#!/usr/bin/env bash
# dl.sh —— 12 并发下 nvidia 轮子（tuna 源，断点续传）
OUT=/root/nvwhl
mkdir -p "$OUT"
cat /root/dl.txt | xargs -P 12 -I{} sh -c '
  f="'"$OUT"'/$(basename {})"
  curl -s -L -C - --retry 8 --retry-delay 2 --max-time 1800 -o "$f" "{}"
  echo "$(date +%T) $(basename {}) $(stat -c %s "$f" 2>/dev/null)"
'
echo "=== ALL DONE $(date +%T) ==="
du -sh "$OUT"
