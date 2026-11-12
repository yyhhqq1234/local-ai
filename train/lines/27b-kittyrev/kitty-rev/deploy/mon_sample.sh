#!/usr/bin/env bash
# gen2 training monitor - single sample (optional leading sleep seconds as $1)
set -u
SLEEP="${1:-0}"
if [ "$SLEEP" -gt 0 ]; then sleep "$SLEEP"; fi
cd "D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/deploy" || exit 1
"C:/ProgramData/anaconda3/python.exe" -X utf8 remote.py --timeout 120 --cmd "cd /root/autodl-tmp/kitty-rev && date '+TS=%H:%M:%S' && echo STEP: && (tr '\r' '\n' < full-run.out | grep -E '[0-9]+/(340|500)' | tail -1) && echo MET: && (tr '\r' '\n' < full-run.out | grep -oE '\{[^{]*loss[^}]*\}' | tail -1) && echo SYS: && nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader && df -h /root/autodl-tmp|tail -1 && echo CKPT: && (ls /root/autodl-tmp/kitty-rev/kitty-rev/out/gen2-nsfw 2>/dev/null | tr '\n' ' ') && echo && echo PROC: && (pgrep -f 'train_[k]itty.py' >/dev/null && echo ALIVE || echo DEAD) && echo DONE: && (tr '\r' '\n' < gen2-full.log | grep -c 'DONE: full') && echo ERR: && (tr '\r' '\n' < full-run.out | grep -ciE \"loss.: .?(nan|inf)|Traceback|CUDA error|out of memory|Killed\")"
