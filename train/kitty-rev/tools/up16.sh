#!/usr/bin/env bash
# up16.sh —— 分块上传 00016（每块 200MB，可重试/可跳过），云端拼回并校验
set -uo pipefail
K=/d/BaiduNetdiskDownload/Local-AI/train/kitty-rev
SRC=$K/tmp/_s16/chunks
RDIR=/root/autodl-tmp/base-hf/Huihui
RBASE=c16.chunk
W=3979564008
cd "$K" || exit 2
export MSYS2_ARG_CONV_EXCL='*'
export AUTODL_HOST=123.127.15.155
export PATH="/c/ProgramData/anaconda3:/c/ProgramData/anaconda3/Scripts:$PATH"

echo "[1/3] 逐块上传 $(date '+%H:%M:%S')"
for f in "$SRC"/c16.*; do
  n=$(basename "$f")
  local_sz=$(stat -c%s "$f")
  for attempt in 1 2 3 4 5; do
    rem=$(python deploy/remote.py --cmd "stat -c%s $RDIR/$n 2>/dev/null || echo 0" 2>/dev/null | tr -d '\r' | tail -1)
    [ -z "$rem" ] && rem=0
    if [ "$rem" = "$local_sz" ]; then echo "  skip $n ($rem)"; break; fi
    echo "  up $n attempt=$attempt local=$local_sz remote=$rem"
    python deploy/remote.py --put "$f" "$RDIR/$n" >/dev/null 2>&1
  done
done

echo "[2/3] 云端拼接 $(date '+%H:%M:%S')"
python deploy/remote.py --cmd "cd $RDIR && rm -f model-00016-of-00018.safetensors && for i in \$(ls c16.* | sort); do cat \$i >> model-00016-of-00018.safetensors; done; s=\$(stat -c%s model-00016-of-00018.safetensors); echo \"merged=\$s want=$W\"; rm -f c16.*" 2>&1 | tail -3

echo "[3/3] 云端 header 校验 $(date '+%H:%M:%S')"
python deploy/remote.py --cmd "cd $RDIR && /root/miniconda3/bin/python -c \"
from safetensors import safe_open
try:
    with safe_open('model-00016-of-00018.safetensors',framework='pt') as h: print('HEADER_OK tensors=',len(list(h.keys())))
except Exception as e: print('HEADER_FAIL',e)
\"" 2>&1 | tail -2
