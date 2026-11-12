#!/usr/bin/env bash
# dl_aria.sh —— aria2c 多连接并行下载 huihui 基座（9 文件并发 × 8 连接）
set -uo pipefail
D=/root/autodl-tmp/base-hf/Huihui
B=https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main
IN=/root/autodl-tmp/base-hf/aria.txt
mkdir -p "$D"
: > "$IN"
if [ ! -s /tmp/_hf_files.txt ]; then
  curl -fsSL --max-time 180 "https://hf-mirror.com/api/models/huihui-ai/Huihui-Qwen3.8-27B-abliterated/tree/main?recursive=1" \
  | /root/miniconda3/bin/python -c "
import json,sys
d=json.load(sys.stdin)
out=[x['path'] for x in d if x.get('type')=='file' and x['path'].endswith(('.safetensors','.json','.jinja','.txt'))]
open('/tmp/_hf_files.txt','w').write('\n'.join(out))
print('files',len(out))
"
fi
while read -r f; do
  [ -z "$f" ] && continue
  printf '%s\n  dir=%s\n  out=%s\n' "$B/$f" "$D" "$f" >> "$IN"
done < /tmp/_hf_files.txt
echo "aria 条目行数: $(wc -l < "$IN")"
echo "启动 aria2c $(date '+%F %T')"
exec aria2c -i "$IN" -j 9 -x 8 -s 8 -c --auto-file-renaming=false --summary-interval=30 --console-log-level=warn
