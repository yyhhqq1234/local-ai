#!/bin/bash
# switch_mirror.sh —— turbo 代理已退化（8 并发实测全 0 字节），切 hf-mirror.net 直连
# 策略：等当前片下完再切（不丢半片），然后 conc=8（mirror 对高并发限流）+ seg=32MB
set -u
R=/root/autodl-tmp/kitty-rev
cd "$R" || exit 1
LOG=$R/logs/v4/SWITCH.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

BEFORE=$(grep -c '\[ok\]' logs/v4/DL2.log 2>/dev/null || echo 0)
log "=== switch start, ok_before=$BEFORE ==="

for i in $(seq 1 28); do
  NOW=$(grep -c '\[ok\]' logs/v4/DL2.log 2>/dev/null || echo 0)
  if [ "$NOW" -gt "$BEFORE" ]; then
    log "当前片已完成（第 $i 次探测，$(($i*15))s）"
    break
  fi
  sleep 15
done

P=$(pgrep -f "^/root/miniconda3/bin/python -u tools/dl_base_fast.py" | head -1 || true)
log "kill_pid=${P:-none}"
if [ -n "${P:-}" ]; then kill "$P" 2>/dev/null; fi
sleep 2
pkill -x curl 2>/dev/null
sleep 2
log "curls_left=$(pgrep -x curl | wc -l)"

# 只删段文件；已完成的 .safetensors 保留（脚本会 skip）
rm -f base/Huihui/*.seg*
log "seg_cleaned done=$(ls base/Huihui/*.safetensors 2>/dev/null | wc -l) shards present"

# 换源：mirror.net 优先
cp -n tools/dl_base_fast.py tools/dl_base_fast.py.bak-host 2>/dev/null || true
sed -i 's|^HOSTS = .*|HOSTS = ["hf-mirror.net", "huggingface.co", "hf-mirror.com"]|' tools/dl_base_fast.py
log "HOSTS now: $(grep -n '^HOSTS' tools/dl_base_fast.py)"

# 不 source turbo：显式清代理
unset https_proxy http_proxy HTTPS_PROXY HTTP_PROXY all_proxy ALL_PROXY
export NO_PROXY="*"
log "proxy_env=[${https_proxy:-none}]"

setsid nohup /root/miniconda3/bin/python -u tools/dl_base_fast.py \
  --out "$R/base/Huihui" --list "$R/tmp/_base/shards.txt" \
  --conc 8 --seg-mb 32 > logs/v4/DL3.log 2>&1 &
NEW=$!
log "new_dl_pid=$NEW"
sleep 45
log "--- DL3 head ---"
head -8 logs/v4/DL3.log
log "--- DL3 tail ---"
tail -3 logs/v4/DL3.log
log "total=$(du -sh base/Huihui | cut -f1) df=$(df -h /root/autodl-tmp | awk 'NR==2{print $4}')"
