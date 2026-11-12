#!/bin/bash
# bump_conc.sh —— mirror 单流 0.875 MB/s，8 并发仅 7 MB/s：提到 16 并发试探
# 顺序：杀旧下载 → 清段 → 起新(conc16) → 立即重启 auto（避免 auto 误判"下载结束"）
set -u
R=/root/autodl-tmp/kitty-rev
cd "$R" || exit 1
LOG=$R/logs/v4/BUMP.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

P=$(pgrep -f "^/root/miniconda3/bin/python -u tools/dl_base_fast.py" | head -1 || true)
log "kill_pid=${P:-none}"
[ -n "${P:-}" ] && kill "$P" 2>/dev/null
sleep 2
pkill -x curl 2>/dev/null
sleep 2
log "curls_left=$(pgrep -x curl | wc -l)"
rm -f base/Huihui/*.seg*
log "shards_present=$(ls base/Huihui/*.safetensors 2>/dev/null | wc -l)"

unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY all_proxy ALL_PROXY
export NO_PROXY="*"
setsid nohup /root/miniconda3/bin/python -u tools/dl_base_fast.py \
  --out "$R/base/Huihui" --list "$R/tmp/_base/shards.txt" \
  --conc 16 --seg-mb 32 > logs/v4/DL4.log 2>&1 &
log "new_dl_pid=$!"

# 立刻重启 auto（它的等待循环按"进程名消失"判定，刚才那 4 秒窗口会误判）
P2=$(pgrep -f '^bash tools/auto_v4r.sh$' || true)
log "auto_old=${P2:-none}"
for p in $P2; do kill "$p" 2>/dev/null; done
sleep 1
setsid nohup bash tools/auto_v4r.sh > /dev/null 2>&1 &
log "auto_new=$!"

sleep 50
log "--- DL4 ---"
tail -4 logs/v4/DL4.log
log "curls=$(pgrep -x curl | wc -l)"
log "total=$(du -sh base/Huihui | cut -f1)"
