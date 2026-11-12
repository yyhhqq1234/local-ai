#!/bin/bash
# auto_v4r.sh —— 云端无人值守总控：等下载 → G1 → 张量级 merge → 全链（含 M1.5 探针）
# 设计前提：操作者在睡觉，lead 只靠 watchdog 心跳被唤醒 ⇒ 关键路径必须脚本自走。
set -u
R=/root/autodl-tmp/kitty-rev
KV=$R/kitty-rev
PY=/root/miniconda3/bin/python
AD=$KV/out-v4/adapter
LOG=$R/logs/v4/AUTO.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

log "===== AUTO v4r start pid=$$ ====="
log "[disk] $(df -h /root/autodl-tmp | tail -1)"

# ---------- 0) 等下载进程退出（最多 100 分钟；硬截止另由 hard_stop 兜底） ----------
for i in $(seq 1 200); do
  if ! pgrep -f dl_base_fast.py > /dev/null; then
    log "下载进程已退出（等待 $((i*30))s）"
    break
  fi
  sleep 30
done
pkill -x curl 2>/dev/null
sleep 2
log "残留 curl=$(pgrep -x curl | wc -l)"

# ---------- 1) G1 硬校验 ----------
if $PY -u tools/g1_check.py --base "$R/base/Huihui" --list "$R/tmp/_base/shards.txt" >> "$LOG" 2>&1; then
  log "[GATE G1] PASS"
else
  log "[GATE G1] FAIL —— 停（看 AUTO.log 尾部）"
  exit 11
fi

# ---------- 2) adapter 断言 ----------
if [ ! -f "$AD/adapter_model.safetensors" ]; then
  log "[FATAL] adapter 不存在: $AD"
  exit 12
fi
AM=$($PY -c "import hashlib;print(hashlib.md5(open('$AD/adapter_model.safetensors','rb').read()).hexdigest())")
log "adapter md5=$AM（期望 11d3d28ed2318749239cdd72bf0f63fe）"
if [ "${AM:0:8}" != "11d3d28e" ]; then
  log "[FATAL] adapter md5 不符，拒绝 merge"
  exit 13
fi

# ---------- 3a) merge dry-run（不写文件、不删 base —— 失败还能救） ----------
log "=== MERGE dry-run（只验 slot 映射，不落盘不删片） ==="
if $PY -u tools/tensor_merge.py --base "$R/base/Huihui" --adapter "$AD" \
      --out "$R/merged-v4" --dry-run >> "$LOG" 2>&1; then
  log "[MERGE] dry-run PASS（交集/命中数见 AUTO.log 的 [pre] 行）"
else
  log "[MERGE] dry-run FAIL —— base 完整未动，可修可重跑"
  exit 16
fi

# ---------- 3b) 张量级 merge（流式：边写边删 base 片） ----------
log "=== MERGE start ==="
if $PY -u tools/tensor_merge.py --base "$R/base/Huihui" --adapter "$AD" \
      --out "$R/merged-v4" --stream >> "$LOG" 2>&1; then
  log "[MERGE] DONE $(du -sh "$R/merged-v4" | cut -f1)"
else
  log "[MERGE] FAIL —— 停"
  exit 14
fi

# ---------- 4) 全链：bf16 → 探针 → q8_0 → imatrix → IQ2_S → splice → convert ----------
log "=== CHAIN start ==="
if $PY -u tools/chain_repair.py --free --free-merged >> "$LOG" 2>&1; then
  NIN=$(ls -1 "$R"/ninfer-v4r/*.ninfer 2>/dev/null | head -1)
  log "[CHAIN] DONE $NIN $(stat -c%s "$NIN" 2>/dev/null) B"
  log "===== AUTO v4r SUCCESS ====="
  exit 0
else
  log "[CHAIN] FAIL —— 看 AUTO.log 里的 [STOP] 行"
  exit 15
fi
