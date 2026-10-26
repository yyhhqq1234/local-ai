log "[P5] struct-align"
$PY /root/autodl-tmp/_ra/verify-struct-align.py "$OUT" >>"$LOG" 2>&1
rc=$?
log "[P5] rc=$rc"
# 审计#6：struct-align 必须阻断 —— 以前只记 rc 继续往下，红件也能走完链
[ $rc -eq 0 ] || { log "[STOP] struct-align rc=$rc（组件/绑定/字节对不上，禁止当交付件）"; exit 1; }
