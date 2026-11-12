#!/bin/bash
# probe_ac.sh - (a) ModelScope search for abliterated 27B + (c) ModelScope baseline throughput.
set -u
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
RANGE="0-8388607"
MB=1048576

echo "############ probe_ac START $(date '+%F %T') ############"

echo
echo "===== [a] ModelScope search API attempts ====="
for u in \
  "https://modelscope.cn/api/v1/dolphin/models?PageSize=30&PageNumber=1&Name=abliterated" \
  "https://modelscope.cn/api/v1/models?PageSize=30&PageNumber=1&Name=abliterated" \
  "https://modelscope.cn/api/v1/dolphin/models?PageSize=30&PageNumber=1&Name=Qwen3.8-27B" ; do
  echo "--- GET $u"
  code=$(curl -s -o /tmp/a.json -w '%{http_code}' --max-time 25 -H "User-Agent: $UA" "$u")
  echo "    HTTP $code  bytes=$(stat -c %s /tmp/a.json 2>/dev/null || echo 0)"
  head -c 900 /tmp/a.json 2>/dev/null; echo
done

echo
echo "===== [a2] HF-mirror / HF search API ====="
for u in \
  "https://hf-mirror.com/api/models?author=huihui-ai&limit=100" \
  "https://hf-mirror.com/api/models?search=abliterated&limit=100" ; do
  echo "--- GET $u"
  code=$(curl -s -o /tmp/a2.json -w '%{http_code}' --max-time 25 -H "User-Agent: $UA" "$u")
  echo "    HTTP $code  bytes=$(stat -c %s /tmp/a2.json 2>/dev/null || echo 0)"
  head -c 1500 /tmp/a2.json 2>/dev/null; echo
done

echo
echo "===== [a3] explicit: does repo exist on ModelScope? ====="
for u in \
  "https://modelscope.cn/api/v1/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated" \
  "https://modelscope.cn/api/v1/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated/repo/files?Revision=master&Root=" ; do
  echo "--- GET $u"
  code=$(curl -s -o /tmp/a3.json -w '%{http_code}' --max-time 25 -H "User-Agent: $UA" "$u")
  echo "    HTTP $code"; head -c 600 /tmp/a3.json 2>/dev/null; echo
done

echo
echo "===== [c] BASELINE: ModelScope Qwen/Qwen3.8-27B ====="
code=$(curl -s -o /tmp/ms.json -w '%{http_code}' --max-time 30 -H "User-Agent: $UA" \
  "https://modelscope.cn/api/v1/models/Qwen/Qwen3.8-27B/repo/files?Revision=master&Root=")
echo "  file-list HTTP $code bytes=$(stat -c %s /tmp/ms.json 2>/dev/null || echo 0)"
CAND=$(grep -o '"Path":"[^"]*\.safetensors"' /tmp/ms.json 2>/dev/null | sed 's/.*:"//;s/"//' | head -3)
if [ -z "$CAND" ]; then
  CAND=$(grep -o '"Name":"[^"]*\.safetensors"' /tmp/ms.json 2>/dev/null | sed 's/.*:"//;s/"//' | head -3)
fi
[ -z "$CAND" ] && CAND="model-00001-of-00009.safetensors model-00001-of-00018.safetensors"
echo "  candidates: $CAND"
for r in 1 2; do
  echo "  -- round $r --"
  for f in $CAND; do
    url="https://modelscope.cn/models/Qwen/Qwen3.8-27B/resolve/master/$f"
    out=$(curl -sS -L --max-time 40 -r "$RANGE" -o /dev/null -H "User-Agent: $UA" \
          -w "%{speed_download} %{http_code} %{size_download}" "$url" 2>/dev/null)
    echo "     $(basename $f)  raw=[$out]" | \
      awk -v o="$out" 'BEGIN{split(o,a," "); printf "%s  %.2f MiB/s http=%s\n", $0, a[1]/1048576, a[2]}' 2>/dev/null || echo "     $f raw=[$out]"
  done
done

echo
echo "############ END $(date '+%F %T') ############"
