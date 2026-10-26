#!/bin/bash
# probe_b.sh - per-domain single-stream throughput, 8 MiB range, 2 rounds. READ-ONLY.
set -u
REPO="huihui-ai/Huihui-Qwen3.8-27B-abliterated"
F="model-00002-of-00018.safetensors"
RANGE="0-8388607"
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'

urls() {
  echo "hf-mirror.com|https://hf-mirror.com/$REPO/resolve/main/$F"
  echo "hf-mirror.net|https://hf-mirror.net/$REPO/resolve/main/$F"
  echo "hf.sukaka.top|https://huggingface.sukaka.top/$REPO/resolve/main/$F"
  echo "hf.xeduapi.com|https://hf.xeduapi.com/$REPO/resolve/main/$F"
  echo "modelscope-hh|https://modelscope.cn/models/$REPO/resolve/master/$F"
}

echo "########## probe_b START $(date '+%F %T') ##########"
echo "-- DNS --"
for h in hf-mirror.com hf-mirror.net huggingface.sukaka.top hf.xeduapi.com modelscope.cn; do
  printf "  %-26s %s\n" "$h" "$(getent hosts $h 2>/dev/null | head -1 | awk '{print $1}')"
done
echo

for r in 1 2; do
  echo "-- round $r (8 MiB each, cap 40s) --"
  urls | while IFS='|' read -r name url; do
    out=$(curl -sS -L --connect-timeout 10 --max-time 40 -r "$RANGE" -o /dev/null \
          -H "User-Agent: $UA" -w "%{speed_download} %{http_code} %{size_download} %{time_total}" \
          "$url" 2>/dev/null)
    printf "  %-18s raw=[%s]\n" "$name" "$out"
  done
  echo
done
echo "########## END $(date '+%F %T') ##########"
