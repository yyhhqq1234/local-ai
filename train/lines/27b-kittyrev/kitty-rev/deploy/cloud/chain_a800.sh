#!/usr/bin/env bash
# chain_a800.sh —— 远端自治链：等基座齐全 → gate1 → 训练 → 打印 adapter 路径
# 设计目的：本机可能随时断（今天断过两次），把"等待 + 判据 + 训练"全放到远端 setsid 里，
#           断线不影响；本机只负责事后取日志与 adapter。
set -uo pipefail
ROOT=/root/autodl-tmp/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
PY=/root/miniconda3/bin/python
L=$ROOT/chain-a800.log
STEPS=${STEPS:-320}
SAVE=${SAVE:-160}

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$L"; }

declare -A WANT=(
 [01]=3966730552 [02]=3043080328 [03]=2542796952 [04]=3988973152 [05]=2099339864
 [06]=3979553696 [07]=2108759344 [08]=3979553696 [09]=2108759344 [10]=3979553696
 [11]=2108759344 [12]=3979553696 [13]=2108759344 [14]=3979553696 [15]=2108759344
 [16]=3979564040 [17]=2108759344 [18]=3392197344
)

log "== 1) 等基座齐全（最长 40 分钟）=="
for i in $(seq 1 80); do
  miss=0
  for k in "${!WANT[@]}"; do
    f="$BASE/model-000${k}-of-00018.safetensors"
    [ "$k" = "18" ] && f="$BASE/model-00018-of-00018.safetensors"
    sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
    if [ "$sz" != "${WANT[$k]}" ]; then miss=$((miss+1)); fi
  done
  if [ "$miss" -eq 0 ]; then log "基座齐全 18/18"; break; fi
  [ $((i % 5)) -eq 0 ] && log "还差 $miss 片…"
  [ "$i" = "80" ] && { log "FATAL 基座 40 分钟未齐，退出"; exit 11; }
  sleep 30
done

# 小文件补齐（tokenizer 等）
for f in config.json generation_config.json tokenizer.json tokenizer_config.json vocab.json \
         merges.txt chat_template.jinja preprocessor_config.json video_preprocessor_config.json \
         model.safetensors.index.json; do
  [ -s "$BASE/$f" ] || log "WARN 缺小文件 $f"
done

log "== 2) gate1：基座直接算 LM loss（必须 0<loss<6；≈12 = 均匀分布 = 废权重）=="
$PY "$ROOT/cloud/hf_lm_loss.py" "$BASE" 2 2>&1 | tee -a "$L" | tail -6 > "$ROOT/gate1.out"
cat "$ROOT/gate1.out" | tee -a "$L"
LOSS=$(grep -oE 'loss=[0-9.]+' "$ROOT/gate1.out" | head -1 | cut -d= -f2)
LOSS=${LOSS:-99}
log "gate1 loss=$LOSS"
$PY -c "import sys;v=float('$LOSS');sys.exit(0 if 0<v<6 else 1)" || { log "FATAL gate1 未过（loss=$LOSS），不训练"; exit 12; }
log "gate1 PASS"

log "== 3) 训练（px ctx2048 bs1 ga16 lr6e-5 r16 a32，${STEPS} 步）=="
STEPS=$STEPS SAVE=$SAVE bash "$ROOT/cloud/gen2_a800.sh" full 2>&1 | tee -a "$L" | tail -3

AD=$(ls -d $ROOT/out/gen2-a800/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
[ -z "$AD" ] && AD="$ROOT/out/gen2-a800/adapter"
log "== 4) adapter 路径: $AD =="
ls -l "$AD" 2>/dev/null | tee -a "$L"
log "== CHAIN DONE =="
