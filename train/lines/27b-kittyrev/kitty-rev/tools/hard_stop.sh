#!/bin/bash
# hard_stop.sh —— 云端硬截止（07:00 前必须停机）
# 用法： bash tools/hard_stop.sh 06:45
#       bash tools/hard_stop.sh cancel      # 取消定时器
#
# 机制：容器内没有 systemd，`shutdown` 通常不可用；退而求其次用 kill -TERM 1
#       让容器主进程退出（AutoDL 侧检测到容器退出即停止实例计费）。
#       本机侧还有 deploy/auto_shutdown.ps1 做第二道保险。
set -eu

R=/root/autodl-tmp/kitty-rev
PIDF=$R/tmp/_hardstop.pid
LOG=$R/logs/v4/HARDSTOP.log
mkdir -p "$(dirname "$LOG")"

if [ "${1:-}" = "cancel" ]; then
  if [ -f "$PIDF" ]; then
    kill "$(cat "$PIDF")" 2>/dev/null || true
    rm -f "$PIDF"
    echo "[cancel] 定时器已取消" | tee -a "$LOG"
  else
    echo "[cancel] 无定时器" | tee -a "$LOG"
  fi
  exit 0
fi

TARGET="${1:-06:45}"
NOW=$(date +%s)
DEAD=$(date -d "$TARGET" +%s)
if [ "$DEAD" -le "$NOW" ]; then
  echo "[FATAL] 目标时刻 $TARGET 已过（now=$(date '+%F %T')）" | tee -a "$LOG"
  exit 2
fi
SLEEP=$((DEAD - NOW))

BODY=$R/tmp/_hardstop_body.sh
mkdir -p "$R/tmp"
cat > "$BODY" <<'EOS'
#!/bin/bash
sleep_secs=$1
logf=$2
sleep "$sleep_secs"
echo "[$(date '+%F %T')] HARD-STOP 触发：sync → kill -TERM 1" >> "$logf" 2>/dev/null
sync
# 依次尝试：shutdown -> poweroff -> halt -> kill init
(command -v shutdown >/dev/null && shutdown -h now) 2>/dev/null || \
(command -v poweroff >/dev/null && poweroff) 2>/dev/null || \
(command -v halt >/dev/null && halt) 2>/dev/null || \
kill -TERM 1
EOS
chmod +x "$BODY"

setsid nohup bash "$BODY" "$SLEEP" "$LOG" >/dev/null 2>&1 &
echo $! > "$PIDF"
{
  echo "[$(date '+%F %T')] 定时器已挂：目标 $TARGET（$SLEEP s 后触发），pid=$(cat "$PIDF")"
  echo "  取消：bash tools/hard_stop.sh cancel"
} | tee -a "$LOG"
