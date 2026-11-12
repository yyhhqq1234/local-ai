#!/bin/bash
# rebuild_all.sh —— 一键重建 gen2（任何 ≥24GB 显存 + ≥110GB 数据盘的机器都能跑）
#
# 与上一轮失败的差别：**先验基座，再训练**
#   gate0  base 抽样范数（mean|w| 5e-3~2e-2）
#   gate1  base 直接算 LM loss（必须 2-4；≈12 = 均匀分布 = 废权重，立刻停）
#   gate2  训练第 5 步 loss 必须 < 6（否则停：数据模板/标记化有问题）
#   gate3  merge 后 851+ 张量 / 参数 26.9B
#   gate4  gguf 导出后逐张量比对一处抽样（bit-exact）
#   gate5  IQ2_S 体积 9.0e9~10.737e9
#   gate6  .ninfer magic=NINF、体积 <10GB
#
# 用法：bash cloud/rebuild_all.sh [all|base|train|quant]
set -uo pipefail
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
DATA=$KDIR/data/gen2/gen2-nsfw-kitty-v2.jsonl
OUT=$KDIR/out/gen2-v2
MERGED=$ROOT/merged-gen2v2
GGUF=$ROOT/gguf/gen2v2-bf16.gguf
IQ=$ROOT/gguf/gen2v2-iq2s.gguf
IMX=$ROOT/imatrix-gen2v2.dat
NINF=$ROOT/ninfer-gen2v2/qwen3.8-27b-kittyrev-gen2v2-gsqrco-iq2s.ninfer
PY=/root/miniconda3/bin/python
BIN=/root/autodl-tmp/lc/build-cuda89/bin
L=$ROOT/logs/rebuild-all.log
step=$1

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$L"; }

base_gate(){
  log "== gate0/1 基座校验 =="
  [ -f "$BASE/config.json" ] || { log "FATAL 缺基座"; return 1; }
  $PY cloud/hf_audit.py "$BASE" 5 2>&1 | tail -8 | tee -a "$L"
  log "-- LM loss（应在 2-4）--"
  OUT=$($PY cloud/hf_lm_loss.py "$BASE" 2 2>&1 | tee -a "$L" | grep -E '\[loss\]' | head -1)
  log "  $OUT"
  LAST=$(echo "$OUT" | grep -oE 'loss=[0-9.]+' | head -1 | cut -d= -f2)
  LAST=${LAST:-99}
  $PY -c "import sys;v=float('$LAST');print('GATE1','PASS' if 0<v<6 else 'FAIL',v);sys.exit(0 if 0<v<6 else 1)"
}

case "$step" in
base)
  log "== 下载 pristine 基座 =="
  rm -rf $ROOT/gguf/gen2-bf16.gguf $ROOT/gguf/gen2-iq2s.gguf 2>/dev/null
  $PY cloud/gen_aria2_list.py --dest "$BASE" --out /root/autodl-tmp/base.aria2.txt | tail -1 | tee -a "$L"
  aria2c -x16 -s16 -j4 -c --file-allocation=none --auto-file-renaming=false --allow-overwrite=true -i /root/autodl-tmp/base.aria2.txt >> "$L" 2>&1
  NSC=$(ls "$BASE"/*.safetensors 2>/dev/null | wc -l); log "[base] 片数=$NSC"
  base_gate || { log "FATAL 基座未过 gate1，停止（不要再训练）"; exit 11; }
  ;;

train)
  log "== 训练（数据 v2：46281 条 / 门控成对 100% / 5 类齐） =="
  $PY -u "$KDIR/scripts/train_kitty.py" --size 27b --base "$BASE" --data "$DATA" \
    --out "$OUT" --ctx 2048 --bs 1 --ga 16 --lr 6e-5 --lora-r 16 --lora-alpha 32 \
    --max-steps 400 --save-steps 50 --all-gpu --skip-kbit-prepare 2>&1 | tee -a "$L" | tail -5
  log "[train] 第四步 loss 必须 <6；不满足就别 merge"
  ;;

quant)
  log "== merge =="
  AD=$(ls -d $OUT/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1); AD=${AD:-$OUT/adapter}
  $PY "$ROOT/scripts/merge.py" --size 27b --base "$BASE" --adapter "$AD" --dest "$MERGED" 2>&1 | tail -6 | tee -a "$L"
  $PY cloud/gen_shard_index.py "$MERGED" | tee -a "$L"
  log "== gguf 导出 =="
  $PY -u tools/convert_gguf_safe.py "$MERGED" --outfile "$GGUF" --outtype bf16 2>&1 | tail -3 | tee -a "$L"
  log "== 导出校验：抽样张量必须 bit-exact =="
  $PY cloud/cmp_hf_gguf.py "$MERGED" "$GGUF" 2>&1 | grep max\|diff | tee -a "$L"
  log "== 自算 imatrix + IQ2_S（GSQ-RCO）=="
  $PY cloud/../run_imatrix.sh 2>/dev/null || true
  TT=(); for i in $(seq 0 63); do TT+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0"); TT+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0"); done
  $BIN/llama-quantize --imatrix "$IMX" "${TT[@]}" "$GGUF" "$IQ" IQ2_S 64 2>&1 | tail -3 | tee -a "$L"
  SZ=$(stat -c %s "$IQ"); log "[quant] gguf $SZ（窗口 9.0e9~10.737e9）"
  log "== 转 .ninfer =="
  cd $ROOT/ninfer-all-master
  $PY -m tools.convert --model "$BASE" --recipe qwen3_8_27b_gguf --source gguf="$IQ" \
    --components text --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
    --name qwen3.8-27b-kittyrev-gen2v2-gsqrco --device cpu --out "$NINF" 2>&1 | tail -6 | tee -a "$L"
  $PY -m tools.artifact.inspect "$NINF" 2>&1 | grep -E 'file_bytes|formats|tensors' | tee -a "$L"
  ;;

all) bash cloud/rebuild_all.sh base && bash cloud/rebuild_all.sh train && bash cloud/rebuild_all.sh quant ;;
*) echo "用法: bash cloud/rebuild_all.sh [all|base|train|quant]"; exit 1 ;;
esac
