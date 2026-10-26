#!/usr/bin/env bash
set -uo pipefail
LOG='/d/BaiduNetdiskDownload/Local-AI/train/kitty-rev/tools/neg6/POST-CHAIN.log'
log(){ echo "$(date "+%F %T") $*" | tee -a "$LOG"; }
PY=/c/Users/Administrator/AppData/Local/Microsoft/WindowsApps/python
OUT=/d/BaiduNetdiskDownload/Local-AI/train/kitty-rev/tools/neg6/ninfer-v4/final2.ninfer
BAD=/d/BaiduNetdiskDownload/Local-AI/train/kitty-rev/tools/neg6/fake_align.py
log "[P5] struct-align"
$PY "$BAD" "$OUT" >>"$LOG" 2>&1
rc=$?
log "[P5] rc=$rc"
# 审计#6：struct-align 必须阻断 —— 以前只记 rc 继续往下，红件也能走完链
[ $rc -eq 0 ] || { log "[STOP] struct-align rc=$rc（组件/绑定/字节对不上，禁止当交付件）"; exit 1; }
log "===== 走到这里说明没阻断（BUG） ====="
