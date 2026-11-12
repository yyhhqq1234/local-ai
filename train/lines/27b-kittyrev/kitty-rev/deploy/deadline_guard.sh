#!/usr/bin/env bash
# deadline_guard.sh —— 硬截止守卫：保证 20:52 前「取完 adapter + 关机」
#
# 逻辑：
#   1) 轮询远端训练进度（gen2-a800-full.log 里的 N/320）
#   2) 若在 20:44 前已到 320 或训练自然结束 → 直接进入取件
#   3) 若 20:44 时步数 < 300 → 认为跑不完，SIGTERM 训练进程，回落最近 checkpoint（160）
#   4) 无论哪条路，20:52 硬截止：先取件（adapter + 全部日志），再关机
#
# 用法：bash deadline_guard.sh            # 后台跑
#      bash deadline_guard.sh --dry      # 只打印当前判定，不动手
set -uo pipefail
cd "$(dirname "$0")" || exit 1
KEY=$HOME/.ssh/autodl_a800
PORT=51211
HOST=root@connect.bjb1.seetacloud.com
SSHOPTS="-i $KEY -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
RR=/root/autodl-tmp/kitty-rev
LOG=D:/BaiduNetdiskDownload/Local-AI/train/logs/deadline-guard.log
HARD=20:52
SOFT=20:42
DRY=${1:-}

log(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
sshx(){ ssh $SSHOPTS "$HOST" "$@"; }

progress(){ sshx "grep -oE '[0-9]+/320' $RR/gen2-a800-full.log 2>/dev/null | tail -1" 2>/dev/null | tr -d '\r'; }
alive(){ sshx "pgrep -c -f train_kitty" 2>/dev/null | tr -d '\r'; }

now_hm(){ date +%H:%M; }
le(){ [ "$(printf '%s\n%s\n' "$1" "$2" | sort | head -1)" = "$1" ]; }   # $1 <= $2

log "=== deadline_guard 启动 硬截止 $HARD / 软线 $SOFT ==="
while :; do
  t=$(now_hm); p=$(progress); a=$(alive)
  log "tick $t 进度=${p:-未知} train_kitty=${a:-0}"
  [ "$DRY" = "--dry" ] && exit 0

  # 训练自然结束？
  if [ "${a:-0}" = "0" ] && [ "${p:-0/320}" = "320/320" ]; then log "训练完成 320/320，进入取件"; break; fi

  # 软线：跑不完就杀掉，回落 ckpt
  if le "$SOFT" "$t" && le "$t" "20:52"; then
    n=${p%%/*}
    if [ "${n:-0}" -lt 290 ]; then
      log "软线到达且步数 $n < 290 → SIGTERM 训练（回落 ckpt-160）"
      sshx "pkill -TERM -f train_kitty; sleep 20; pkill -KILL -f train_kitty 2>/dev/null; echo killed" >/dev/null 2>&1
      break
    fi
    log "软线到达但步数 $n >= 290 → 等它跑完（最多 7 分钟，硬截止前必须收）"
    for i in $(seq 1 14); do
      sleep 30
      p=$(progress); [ "${p:-}" = "320/320" ] && break
      [ "$(alive)" = "0" ] && break
    done
    break
  fi

  # 硬截止兜底
  if le "$HARD" "$t"; then log "硬截止到达，停止等待，直接取件"; break; fi
  sleep 60
done

log "=== 取件（adapter + 日志）==="
mkdir -p D:/BaiduNetdiskDownload/Local-AI/train/logs/a800-final
bash fetch_adapter.sh 2>&1 | tee -a "$LOG" | tail -8
for f in kitty-rev/chain-a800.log kitty-rev/gen2-a800-full.log kitty-rev/gate1.out; do
  scp -i $KEY -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      "$HOST:/root/autodl-tmp/$f" "D:/BaiduNetdiskDownload/Local-AI/train/logs/a800-final/$(basename $f)" >/dev/null 2>&1 \
      && log "  取回 $(basename $f)" || log "  取不到 $f（可忽略）"
done

log "=== 关机 ==="
AUTODL_HOST=$HOST:$PORT AUTODL_PASS=UYGNSRWWiAvn \
  "C:/ProgramData/anaconda3/python.exe" -X utf8 autodl_power.py off --force 2>&1 | tee -a "$LOG" | tail -4
log "=== DONE $(date '+%H:%M:%S') ==="
