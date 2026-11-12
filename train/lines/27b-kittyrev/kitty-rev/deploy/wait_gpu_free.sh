#!/usr/bin/env bash
# wait_gpu_free.sh -- poll the AutoDL box until the GPU is free (training done).
# Criterion switched from pgrep to nvidia-smi: pgrep -f matches the ssh bash -c
# wrapper itself and torch._inductor spawns 32 compile workers, so process
# counting is unreliable. GPU compute-app list is the real gate for starting serve.
# Read-only on the remote side.
set -u
cd "D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/deploy" || exit 1
export MSYS2_ARG_CONV_EXCL='*'
PY='C:/ProgramData/anaconda3/python.exe'

CMD="nvidia-smi --query-compute-apps=pid --format=csv,noheader | wc -l; nvidia-smi --query-gpu=memory.used --format=csv,noheader; ls /root/autodl-tmp/kitty-rev/out/adapter/adapter_config.json 2>/dev/null && echo ADAPTER_OK || echo ADAPTER_MISSING"

for i in $(seq 1 180); do
  raw=$("$PY" remote.py --cmd "$CMD" 2>&1 | tr -d '\r')
  apps=$(echo "$raw" | sed -n '1p' | tr -dc '0-9')
  used=$(echo "$raw" | sed -n '2p' | tr -dc '0-9')
  [ -z "$apps" ] && apps="?"
  [ -z "$used" ] && used="?"
  if echo "$raw" | grep -q ADAPTER_OK; then ad="ADAPTER_OK"; else ad="ADAPTER_MISSING"; fi
  echo "[wait] #$i apps=$apps vram=${used}MiB $ad at $(date '+%T')"
  if [ "$apps" = "0" ] && [ "$used" -lt 3000 ] 2>/dev/null; then
    echo "[wait] GPU FREE at $(date '+%F %T')"
    echo "$raw"
    exit 0
  fi
  sleep 45
done
echo "[wait] TIMEOUT after 180 checks"
exit 2
