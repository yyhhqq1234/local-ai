#!/usr/bin/env bash
# gen3_chain.sh —— 远端自治链（5090）：pre → gate1 → smoke(OOM 回落) → full → 落 DONE
#
# 设计：本机可能断线，全部逻辑放远端 setsid；本机只轮询 STATUS 文件 + 取 adapter + 关机。
# 状态文件 $ROOT/gen3-status.txt 每步覆写：PRE/GATE/SMOKE/TRAIN/DONE/FAIL:<原因>
set -uo pipefail
ROOT=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
L=$ROOT/gen3-chain.log
S=$ROOT/gen3-status.txt
STEPS=${STEPS:-2800}
SAVE=${SAVE:-400}

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$L"; }
status(){ echo "$1" > "$S"; log "STATUS=$1"; }
fail(){ status "FAIL:$1"; exit 90; }

status PRE
bash $ROOT/cloud/gen3_5090.sh pre 2>&1 | tee -a "$L" | tail -20
grep -q "MATMUL OK" "$L" || fail "sm120-matmul"
N=$(wc -l < $ROOT/kitty-rev/data/gen2/gen3-nsfw-kitty.jsonl 2>/dev/null || echo 0)
log "数据行数=$N"; [ "$N" -gt 46000 ] || fail "data-short:$N"

status GATE
bash $ROOT/cloud/gen3_5090.sh gate 2>&1 | tee -a "$L" | tail -8 || fail "gate1"

status SMOKE
BS=2 GA=8 bash $ROOT/cloud/gen3_5090.sh smoke 2>&1 | tee -a "$L" | tail -30
if grep -qiE "out of memory|CUDA out of memory|OutOfMemoryError" "$ROOT/gen3-5090-smoke.log" 2>/dev/null; then
  log "smoke bs2 OOM → 回落 bs1/ga16 重试"
  BS=1 GA=16 bash $ROOT/cloud/gen3_5090.sh smoke 2>&1 | tee -a "$L" | tail -20
  grep -qiE "out of memory" "$ROOT/gen3-5090-smoke.log" && fail "smoke-oom-bs1"
  export BS=1 GA=16
else
  # smoke 步速采样（判据：单步 <60s，否则卡死）
  SP=$(grep -oE "[0-9.]+s/it|[0-9.]+s/step" "$ROOT/gen3-5090-smoke.log" | tail -3 | head -1)
  log "smoke 步速样本=$SP"
fi

status TRAIN
log "开始全量训练 steps=$STEPS save=$SAVE BS=${BS:-2} GA=${GA:-8}"
BS=${BS:-2} GA=${GA:-8} STEPS=$STEPS SAVE=$SAVE \
  bash $ROOT/cloud/gen3_5090.sh full 2>&1 | tee -a "$L" | tail -5

AD=$(ls -d $ROOT/out/gen3/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
[ -z "$AD" ] && AD="$ROOT/out/gen3/adapter"
if [ -f "$AD/adapter_model.safetensors" ]; then
  SZ=$(stat -c %s "$AD/adapter_model.safetensors")
  log "adapter=$AD size=$SZ"
  [ "$SZ" -gt 100000000 ] || fail "adapter-too-small:$SZ"
  status "DONE:$AD"
else
  fail "no-adapter"
fi
log "== CHAIN DONE =="
