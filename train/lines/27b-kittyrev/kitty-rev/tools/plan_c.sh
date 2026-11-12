#!/bin/bash
# plan_c.sh —— 04:45 熔断：中止 imatrix，复用旧 imatrix-v4.dat 起 M4
# 设计依据（watchdog 2026-10-24 复核）：
#   ① 先杀子（imatrix）再杀父（chain），避免孤儿进程
#   ② cp 必须确认 imatrix 死透后再做 —— 它持有 27MB 缓冲，未死透会回写覆盖新 cp 的文件
#   ③ M3.ok 内容显式写 REUSED-OLD，不伪装成"重算完成"
set -u
R=/root/autodl-tmp/kitty-rev
cd "$R" || exit 1
LOG=$R/logs/v4/PLAN-C.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

IMX_PID=$(pgrep -f "^/root/autodl-tmp/lc/build-cuda89/bin/llama-imatrix" | head -1 || true)
CHAIN_PID=$(pgrep -f "tools/chain_repair.py" | head -1 || true)
log "imatrix_pid=${IMX_PID:-none} chain_pid=${CHAIN_PID:-none}"

# ① 先杀子
if [ -n "${IMX_PID:-}" ]; then kill "$IMX_PID" 2>/dev/null; log "killed imatrix $IMX_PID"; fi
sleep 2
# ② 再杀父
if [ -n "${CHAIN_PID:-}" ]; then kill "$CHAIN_PID" 2>/dev/null; log "killed chain $CHAIN_PID"; fi
sleep 1

# ③ 等死透（最多 20s），未死透则拒绝 cp
for i in $(seq 1 10); do
  N=$(pgrep -f "llama-imatrix" | wc -l)
  [ "$N" -eq 0 ] && break
  log "waiting imatrix exit... ($N 个仍在，第 $i 次)"
  sleep 2
done
N=$(pgrep -f "llama-imatrix" | wc -l)
if [ "$N" -ne 0 ]; then
  log "[FATAL] imatrix 未死透（$N 个），拒绝 cp —— 否则旧件会被半截新文件覆盖"
  exit 11
fi
log "imatrix 已死透（0 个）"

# ④ cp 旧件 + 自证
if [ ! -f imatrix-v4.dat ]; then log "[FATAL] 旧件 imatrix-v4.dat 不存在"; exit 12; fi
cp -f imatrix-v4.dat imatrix-v4r.dat
SZ=$(stat -c%s imatrix-v4r.dat)
MD5=$(md5sum imatrix-v4r.dat | cut -d' ' -f1)
OLD_MD5=$(md5sum imatrix-v4.dat | cut -d' ' -f1)
log "copied imatrix-v4.dat → imatrix-v4r.dat  bytes=$SZ md5=$MD5"
if [ "$MD5" != "$OLD_MD5" ]; then log "[FATAL] md5 与源不一致"; exit 13; fi
log "md5 双端一致 OK"

# ⑤ 标记（显式降级）
echo "REUSED-OLD src=imatrix-v4.dat(bad-weight 2026-10-23) cp_at=$(date +%H:%M) bytes=$SZ md5=$MD5" \
  > logs/v4/.markers-r/M3.ok
log "M3.ok 已写（REUSED-OLD）"

# ⑥ 续跑 M4
setsid nohup /root/miniconda3/bin/python -u tools/chain_repair.py --from M4 > logs/v4/CHAIN-R5.log 2>&1 &
log "chain resumed --from M4 pid=$!"
sleep 20
log "--- CHAIN-R5 head ---"
head -8 logs/v4/CHAIN-R5.log 2>/dev/null
