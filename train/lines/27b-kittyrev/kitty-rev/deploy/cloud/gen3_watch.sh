#!/usr/bin/env bash
# gen3_watch.sh —— 盯训练进程退出，写 DONE/FAIL 到 gen3-status.txt（供本机 gen3_guard.py 收口关机）
ROOT=/root/autodl-tmp/kitty-rev
S=$ROOT/gen3-status.txt
L=$ROOT/gen3-watch.log
PIDF=$(pgrep -f 'train_kitty.py .*--out /root/autodl-tmp/kitty-rev/out/gen3' | head -1)
echo "[$(date +%T)] watch start pid=$PIDF" >> "$L"
while kill -0 "$PIDF" 2>/dev/null; do sleep 60; done
echo "[$(date +%T)] pid $PIDF exited" >> "$L"
AD=$(ls -d $ROOT/out/gen3/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
[ -z "$AD" ] && AD="$ROOT/out/gen3/adapter"
if [ -f "$AD/adapter_model.safetensors" ]; then
  SZ=$(stat -c %s "$AD/adapter_model.safetensors")
  echo "DONE:$AD" > "$S"
  echo "[$(date +%T)] DONE $AD $SZ" >> "$L"
else
  echo "FAIL:no-adapter" > "$S"
  echo "[$(date +%T)] FAIL no adapter" >> "$L"
fi
