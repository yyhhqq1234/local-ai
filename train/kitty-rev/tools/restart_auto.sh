#!/bin/bash
# restart_auto.sh —— 按精确 cmdline 重启 auto 总控（避免 pkill -f 自杀）
R=/root/autodl-tmp/kitty-rev
cd "$R" || exit 1

PIDS=$(pgrep -f '^bash tools/auto_v4r.sh$' || true)
echo "old_pids=[$PIDS]"
for p in $PIDS; do
  kill "$p" 2>/dev/null
done
sleep 1
LEFT=$(pgrep -f '^bash tools/auto_v4r.sh$' | wc -l)
echo "left_after_kill=$LEFT"

setsid nohup bash tools/auto_v4r.sh > /dev/null 2>&1 &
NEW=$!
echo "new_auto_pid=$NEW"
sleep 5

echo "dryrun_lines=$(grep -c 'dry-run' tools/auto_v4r.sh || echo 0)"
echo "alive=$(pgrep -f '^bash tools/auto_v4r.sh$' | wc -l)"
echo "--- AUTO.log ---"
tail -3 logs/v4/AUTO.log
echo "--- dl ---"
tail -1 logs/v4/DL2.log
du -sh base/Huihui
df -h /root/autodl-tmp | tail -1
