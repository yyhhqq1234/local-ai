#!/usr/bin/env bash
# get16_local.sh —— 本地 8 路分段下载 model-00016 这片（HF mirror 对单连接限速，本地多连接更快）
set -uo pipefail
W=3979564008
N=8
URL=https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main/model-00016-of-00018.safetensors
OUT=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/tmp/_s16
rm -rf "$OUT"; mkdir -p "$OUT"
CH=$(( (W + N - 1) / N ))
echo "[1/3] 8 路分段下载（每段 $((CH/1048576)) MB）$(date '+%H:%M:%S')"
for i in $(seq 0 $((N-1))); do
  s=$(( i * CH )); e=$(( s + CH - 1 )); [ "$e" -ge "$W" ] && e=$((W-1))
  ( curl.exe -sL --retry 6 --retry-all-errors --connect-timeout 15 --max-time 1800 \
      -r ${s}-${e} -o "$OUT/part$i" "$URL"; echo "seg$i $(stat -c%s "$OUT/part$i" 2>/dev/null||echo 0)" ) &
done
wait
echo "[2/3] 拼接 $(date '+%H:%M:%S')"
: > "$OUT/model-00016-of-00018.safetensors"
for i in $(seq 0 $((N-1))); do cat "$OUT/part$i" >> "$OUT/model-00016-of-00018.safetensors"; done
SZ=$(stat -c%s "$OUT/model-00016-of-00018.safetensors")
echo "   合并后 size=$SZ  期望=$W"
[ "$SZ" -eq "$W" ] || { echo "[FAIL] size 不符"; exit 1; }
echo "[3/3] 校验 header $(date '+%H:%M:%S')"
/c/ProgramData/anaconda3/python.exe -X utf8 -c "
import sys
from safetensors import safe_open
p=r'$OUT/model-00016-of-00018.safetensors'
try:
    with safe_open(p,framework='pt') as f: print('HEADER_OK tensors=',len(list(f.keys())))
except Exception as e: print('HEADER_FAIL',e); sys.exit(1)
"
