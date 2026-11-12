#!/usr/bin/env bash
# 9B 线 out/ 目录清理：以 z-re-v4 为基础，r3 保留，其余按成绩清
#
# 保留（核心成品）
#   z-re-v4/final          kitty 腿最好成绩 30/40 · 75.0% · 编造 0
#   re-stage1-r3/final     r3 基线（操作者要求保留）
#   z-2a-v7/final          编码腿成品 cov 0.6462（PASS）
#   2b-nsfw-v2/final       门控当前最好（FPR 0.375，虽 FAIL 但作对照基线）
#
# 清理（成绩不如 v4 / 数据作废 / 方案已证伪）
#   2b-nsfw/        4.3G  v1 · FPR 1.0 最差
#   2b-nsfw-v4/     6.8G  数据含 20 条评测泄漏 → 作废
#   z-re-v7/        4.9G  29/40，不如 v4；权重还是 fp32（331MB）
#   z-re-v5/        3.2G  29/40，不如 v4
#   mix-v5/ mix-v8/ 各186M 单 adapter 混合方案，两次实证泄漏 42.5-47.5%，已证伪
#   z-re-v6/        1K    空目录（v6 未训）
#
# 另：清 2b-nsfw-v2 与 z-2a-v7 的 checkpoint，各保留 final（省约 10 GB）
set -u
DRY=1
[ "${1:-}" = "--apply" ] && DRY=0
cd "$(dirname "$0")/../../.." || exit 1
O=train/lines/9b-oxcoder/out
L=train/logs/cleanup-out.log
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$L"; }

# 保护项硬校验：这些路径绝不允许出现在删除列表里
PROTECTED="train/lines/9b-oxcoder/models train/lines/27b-kittyrev train/.venv ninfer-csunx ninfer-27b plugins _work/session-audit"

DEL_DIRS="2b-nsfw 2b-nsfw-v4 z-re-v7 z-re-v5 mix-v5 mix-v8 z-re-v6"
CKPT_STRIP="2b-nsfw-v2 z-2a-v7"

log "================ 清理开始（$([ $DRY -eq 1 ] && echo DRY-RUN || echo APPLY)）================"
total=0
for d in $DEL_DIRS; do
  p="$O/$d"
  [ -d "$p" ] || { log "  跳过（不存在）$d"; continue; }
  # 保护校验
  skip=0
  for prot in $PROTECTED; do
    case "$p" in "$prot"*) skip=1;; esac
  done
  [ $skip -eq 1 ] && { log "  ✗ 保护项，拒绝删除：$p"; continue; }
  sz=$(du -sm "$p" 2>/dev/null | cut -f1)
  total=$((total + sz))
  if [ $DRY -eq 1 ]; then
    log "  [DRY] 将删 $d  (${sz} MB)"
  else
    rm -rf "$p" && log "  已删 $d  (${sz} MB)"
  fi
done

for d in $CKPT_STRIP; do
  p="$O/$d"
  [ -d "$p/final" ] || { log "  跳过 $d（无 final，不清 checkpoint）"; continue; }
  n=$(ls -d "$p"/checkpoint-* 2>/dev/null | wc -l)
  [ "$n" -eq 0 ] && continue
  sz=$(du -sm "$p" 2>/dev/null | cut -f1)
  fsz=$(du -sm "$p/final" 2>/dev/null | cut -f1)
  save=$((sz - fsz))
  total=$((total + save))
  if [ $DRY -eq 1 ]; then
    log "  [DRY] $d：清 $n 个 checkpoint，保留 final（省 ${save} MB）"
  else
    rm -rf "$p"/checkpoint-* && log "  $d：已清 $n 个 checkpoint，保留 final（省 ${save} MB）"
  fi
done

log "【合计】可释放约 ${total} MB ≈ $((total / 1024)) GB"
log "【保留】z-re-v4/final · re-stage1-r3/final · z-2a-v7/final · 2b-nsfw-v2/final"
log "================ 清理结束 ================"
if [ $DRY -eq 1 ]; then
  echo
  echo "确认无误后执行：bash $0 --apply"
fi
