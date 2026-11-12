#!/usr/bin/env bash
# 2B 门控评测分片跑（应对「跑到约 20 条进程消失」的问题）
# 每片独立进程 + 独立落盘 + 日志实时；最后用 _merge_gate_shards.py 合并
set -u
cd "$(dirname "$0")/../../.." || exit 1        # → 仓库根
PY=./train/.venv/Scripts/python.exe
S=train/lines/_shared/scripts
D=train/lines/9b-oxcoder/data
L=train/logs
O=train/lines/9b-oxcoder/out
ADAPTER="${1:-$O/2b-nsfw-v2/final}"
TAG="${2:-v2b}"
SH="${3:-12}"                                   # 每片条数（12 实测能跑完）
MAXNEW="${4:-512}"                              # 生成上限（512 会让长文本在铺垫处截断）
TOTAL=85
LOG="$L/gate-shard-$TAG.log"

: > "$LOG"
echo "[$(date '+%F %T')] 分片评测 adapter=$ADAPTER tag=$TAG shard=$SH" | tee -a "$LOG"

off=0
while [ "$off" -lt "$TOTAL" ]; do
  echo "[$(date '+%T')] ---- shard off=$off limit=$SH ----" | tee -a "$LOG"
  PYTHONIOENCODING=utf-8 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
    "$PY" -u "$S/nsfw_gate_local.py" \
      --adapter "$ADAPTER" \
      --val "$D/eval/val/nsfw-gate.jsonl" \
      --offset "$off" --limit "$SH" --max-new "$MAXNEW" \
      --out "$L/gate-$TAG-shard-$off.json" >> "$LOG" 2>&1
  rc=$?
  echo "[$(date '+%T')] shard off=$off rc=$rc" | tee -a "$LOG"
  off=$((off + SH))
done

echo "[$(date '+%F %T')] 全部分片结束 → 合并" | tee -a "$LOG"
PYTHONIOENCODING=utf-8 "$PY" -u "$S/_merge_gate_shards.py" --tag "$TAG" --adapter "$ADAPTER" --total "$TOTAL" >> "$LOG" 2>&1
echo "[$(date '+%F %T')] 合并 rc=$?" | tee -a "$LOG"
tail -20 "$LOG"
