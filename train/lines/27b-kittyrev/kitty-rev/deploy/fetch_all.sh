#!/usr/bin/env bash
# fetch_all.sh —— 串行拉回三个交付物（32 流 + md5 校验）
set -uo pipefail
cd "$(dirname "$0")"
PY='C:/ProgramData/anaconda3/python.exe'
DEST='D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/local-pack'
RHOST='/root/autodl-tmp/kitty-rev'
mkdir -p "$DEST"

run() {
  local name="$1" remote="$2" local_="$3" streams="$4"
  echo "======== $(date +%H:%M:%S) START $name (streams=$streams) ========"
  "$PY" get_multi.py --remote "$remote" --local "$local_" --streams "$streams" 2>&1 | tail -6
  local rc=$?
  if [ -f "$local_" ]; then
    ls -l "$local_" | awk '{print "  size:", $5}'
  fi
  echo "======== $(date +%H:%M:%S) END $name rc=$rc ========"
}

run adapter "$RHOST/out/adapter-full3ep/adapter_model.safetensors" \
            "$DEST/adapter_model.safetensors" 4
run config  "$RHOST/out/adapter-full3ep/adapter_config.json" \
            "$DEST/adapter_config.json" 1
run ninfer  "$RHOST/ninfer/qwen3_8_27b_kittyrev.ninfer" \
            "$DEST/qwen3_8_27b_kittyrev.ninfer" 32
run conv    "$RHOST/ninfer/qwen3_8_27b_kittyrev.ninfer.conversion.json" \
            "$DEST/qwen3_8_27b_kittyrev.ninfer.conversion.json" 1
run pack    "$RHOST/kittyrev-local-pack.tar" \
            "$DEST/kittyrev-local-pack.tar" 32

echo "======== $(date +%H:%M:%S) ALL DONE ========"
ls -lh "$DEST"
