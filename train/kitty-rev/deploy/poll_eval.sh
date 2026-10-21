#!/usr/bin/env bash
# poll_eval.sh -- watch the eval log until the summary line appears.
set -u
cd "D:/BaiduNetdiskDownload/Local-AI/train/kitty-rev/deploy" || exit 1
export MSYS2_ARG_CONV_EXCL='*'
PY='C:/ProgramData/anaconda3/python.exe'
L=/root/autodl-tmp/kitty-rev/logs/eval-base-repro.log

for i in $(seq 1 90); do
  out=$("$PY" remote.py --cmd "grep -a '总通过' $L 2>/dev/null | tail -2; echo '--PROGRESS--'; grep -ac 'PASS\|FAIL' $L 2>/dev/null; tail -2 $L 2>/dev/null" 2>&1 | tr -d '\r')
  echo "=== poll #$i $(date '+%T') ==="
  echo "$out"
  if echo "$out" | grep -q '总通过'; then
    echo "=== EVAL DONE $(date '+%T') ==="
    "$PY" remote.py --cmd "cat /root/autodl-tmp/kitty-rev/logs/serve-eval-run.log; echo '--- peak ---'; cat /root/autodl-tmp/kitty-rev/logs/vram-peak.txt" 2>&1 | tr -d '\r'
    exit 0
  fi
  sleep 60
done
echo "=== POLL TIMEOUT ==="
exit 2
