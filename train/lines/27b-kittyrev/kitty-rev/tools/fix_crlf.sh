#!/bin/bash
# fix_crlf.sh —— 清 CRLF、修语法、重启 auto 总控（自身也需被 tr 处理一次再跑）
R=/root/autodl-tmp/kitty-rev
cd "$R" || exit 1
pkill -f auto_v4r.sh 2>/dev/null
sleep 1
for f in tools/auto_v4r.sh tools/hard_stop.sh tools/g1_check.py tools/chain_repair.py tools/tensor_merge.py tools/dl_base_fast.py; do
  if [ -f "$f" ]; then
    tr -d '\r' < "$f" > "$f.t" && mv "$f.t" "$f"
  fi
done
CR=$(tr -cd '\r' < tools/auto_v4r.sh | wc -c)
echo "CR_left=$CR"
if bash -n tools/auto_v4r.sh; then echo BASH_OK; else echo BASH_BAD; exit 2; fi
if /root/miniconda3/bin/python -m py_compile tools/g1_check.py tools/chain_repair.py tools/tensor_merge.py; then
  echo PY_OK
else
  echo PY_BAD; exit 3
fi
setsid nohup bash tools/auto_v4r.sh > /dev/null 2>&1 &
echo auto_pid=$!
sleep 6
echo "--- AUTO.log ---"
tail -3 logs/v4/AUTO.log
echo "alive=$(pgrep -f auto_v4r.sh | wc -l)"
echo "--- dl ---"
tail -1 logs/v4/DL2.log
du -sh base/Huihui
df -h /root/autodl-tmp | tail -1
