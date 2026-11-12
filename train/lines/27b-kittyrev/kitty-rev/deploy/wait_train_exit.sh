#!/usr/bin/env bash
# wait_train_exit.sh -- poll the AutoDL box until the smoke training process exits.
# Read-only on the remote side (pgrep only). Does NOT start any GPU job.
set -u
cd "D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/deploy" || exit 1
export MSYS2_ARG_CONV_EXCL='*'
PY='C:/ProgramData/anaconda3/python.exe'

for i in $(seq 1 120); do
  n=$("$PY" remote.py --cmd "pgrep -af train_kitty.py | grep python | wc -l" 2>&1 | tr -d '\r' | tail -1)
  n=$(echo "$n" | tr -dc '0-9')
  [ -z "$n" ] && n="?"
  if [ "$n" = "0" ]; then
    echo "[wait] train exited, check #$i at $(date '+%F %T')"
    "$PY" remote.py --cmd "nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader; ls -l /root/autodl-tmp/kitty-rev/out/ 2>&1; ls -l /root/autodl-tmp/kitty-rev/out/adapter 2>&1 | head -6" 2>&1 | tr -d '\r'
    exit 0
  fi
  echo "[wait] #$i train_kitty procs=$n at $(date '+%T')"
  sleep 60
done
echo "[wait] TIMEOUT after 120 checks"
exit 2
