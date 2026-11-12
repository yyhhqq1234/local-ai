#!/usr/bin/env bash
# post_chain.sh —— 量化后收口：splice_new(arch 已验) → convert(text,mtp) → 结构与名字自检
set -uo pipefail
R=/root/autodl-tmp/kitty-rev
IQ2S=$R/gguf/v4-iq2s-851.gguf
REF=/root/autodl-tmp/ref/ref_sparse.gguf
MTP=$R/gguf/mtp-spliced/v4_mtp_s.gguf
OUT=$R/ninfer-v4/final2.ninfer
NAME=qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-abliterated-iq2s-mtp   # 定稿名（四要素：swift1.5/gsq/rco/abliterated）
PY=/root/miniconda3/bin/python
LOG=$R/logs/v4/POST-CHAIN.log
log(){ echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

log "===== post_chain start ====="
[ -f "$IQ2S" ] || { log "[STOP] 无 IQ2_S"; exit 1; }
log "[P1] IQ2_S bytes=$(stat -c%s "$IQ2S")"

mkdir -p "$R/gguf/mtp-spliced"
rm -f "$MTP"
log "[P2] splice_new"
$PY "$R/tools/splice_new.py" --base "$IQ2S" --ref "$REF" --out "$MTP" >>"$LOG" 2>&1
rc=$?
[ $rc -eq 0 ] || { log "[STOP] splice rc=$rc"; exit 1; }
log "[P2] PASS $(stat -c%s "$MTP") B"

cd "$R/ninfer-all-master"
log "[P3] convert text,mtp"
$PY -m tools.convert --model "$R/cfg-vision" --recipe qwen3_8_27b_gguf \
   --source gguf="$MTP" --components text,mtp --name "$NAME" --out "$OUT" >>"$LOG" 2>&1
rc=$?
[ $rc -eq 0 ] || { log "[STOP] convert rc=$rc"; exit 1; }
log "[P3] convert done bytes=$(stat -c%s "$OUT")"

log "[P4] inspect name"
$PY -m tools.artifact.inspect "$OUT" --json 2>/dev/null | head -6 >>"$LOG"
log "[P5] struct-align"
$PY /root/autodl-tmp/_ra/verify-struct-align.py "$OUT" >>"$LOG" 2>&1
rc=$?
log "[P5] rc=$rc"
# 审计#6：struct-align 必须阻断 —— 以前只记 rc 继续往下，红件也能走完链
[ $rc -eq 0 ] || { log "[STOP] struct-align rc=$rc（组件/绑定/字节对不上，禁止当交付件）"; exit 1; }
log "===== post_chain DONE out=$OUT ====="
