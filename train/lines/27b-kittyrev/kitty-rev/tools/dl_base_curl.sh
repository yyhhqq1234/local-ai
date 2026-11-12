#!/usr/bin/env bash
# dl_base_curl.sh —— hf-mirror 直链并行下载 huihui 基座（绕开 hf_hub 的 httpx2 解码 bug）
# 只用 curl -C -（断点续传），8 路并发，落 /root/autodl-tmp/base-hf/Huihui
set -uo pipefail
DST=/root/autodl-tmp/base-hf/Huihui
BASE="https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main"
mkdir -p "$DST"
cd "$DST"

echo "[1/3] 取文件清单 $(date '+%F %T')"
curl -fsSL --max-time 60 "https://hf-mirror.com/api/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated/tree/main?recursive=1" \
 | /root/miniconda3/bin/python -c "
import json,sys
d=json.load(sys.stdin)
fs=[x['path'] for x in d if x.get('type')=='file']
keep=[f for f in fs if f.endswith(('.safetensors','.json','.jinja','.txt')) and not f.endswith('.pth')]
print('\n'.join(keep))
" > /tmp/_hf_files.txt
echo "  文件数=$(wc -l < /tmp/_hf_files.txt)"; head -5 /tmp/_hf_files.txt

echo "[2/3] 并行下载（8 路，curl -C - 续传）"
cat /tmp/_hf_files.txt | xargs -P 8 -I{} bash -c '
  f="{}"; out="'"$DST"'/$f"
  mkdir -p "$(dirname "$out")"
  [ -s "$out" ] && sz=$(stat -c%s "$out") || sz=0
  curl -fsSL -C - --retry 5 --retry-all-errors --connect-timeout 20 --max-time 7200 \
       -o "$out" "'"$BASE"'/$f" 2>/dev/null
  rc=$?
  printf "%s rc=%s bytes=%s\n" "$f" "$rc" "$(stat -c%s "$out" 2>/dev/null || echo 0)"
' | tee /root/autodl-tmp/base-hf/dl_files.log | tail -20

echo "[3/3] 汇总 $(date '+%F %T')"
du -sh "$DST"
ls -la "$DST" | head -20
