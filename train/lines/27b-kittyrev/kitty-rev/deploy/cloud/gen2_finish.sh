#!/usr/bin/env bash
# gen2_finish.sh —— 第 2 代收口：merge(bf16) → 补 index → 释放 base → 转 .ninfer(纯文本) → 结构自检
#
# 前置：训练被 03:35 裸停，adapter 取最新 checkpoint-N（SFTTrainer 的 checkpoint 本身是合规 PEFT adapter）
# 用法：
#   bash gen2_finish.sh check                       # 体检（adapter 完整性 / 空间账 / 最新 ckpt）
#   bash gen2_finish.sh merge  <adapter_dir>        # CPU 合并 bf16（约 35 分钟）
#   bash gen2_finish.sh convert                     # 转 .ninfer（约 10 分钟，纯文本）
set -uo pipefail

ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/merged-v61
OUTD=$KDIR/out/gen2-nsfw
MERGED=$ROOT/merged-gen2
NINFER_DIR=$ROOT/ninfer-gen2
NINFER=$NINFER_DIR/qwen3.8-27b-kittyrev-gen2-iq2s.ninfer
PY=${PY:-/root/miniconda3/bin/python}

case "${1:-check}" in
check)
  echo "== 最新 checkpoint =="
  ls -d $OUTD/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -3 || echo "(无 checkpoint)"
  echo "== out/adapter =="
  ls -l "$OUTD/adapter/adapter_model.safetensors" 2>/dev/null || echo "(训练未到终点，用 checkpoint)"
  echo "== base ==";  ls "$BASE/config.json" 2>/dev/null || echo "MISSING base"
  echo "== disk ==";  df -h /root/autodl-tmp | tail -1
  ;;

merge)
  ADAPTER=${2:-}
  if [ -z "$ADAPTER" ]; then
    ADAPTER=$(ls -d $OUTD/checkpoint-* 2>/dev/null | sort -t- -k2 -n | tail -1)
    [ -z "$ADAPTER" ] && ADAPTER=$OUTD/adapter
  fi
  echo "[merge] base=$BASE"
  echo "[merge] adapter=$ADAPTER"
  ls -l "$ADAPTER/adapter_model.safetensors" || { echo "[FATAL] adapter 不完整"; exit 1; }
  $PY "$ROOT/scripts/merge.py" --size 27b --base "$BASE" --adapter "$ADAPTER" --dest "$MERGED" 2>&1 | tail -20
  [ -f "$MERGED/config.json" ] || { echo "[FATAL] merge 失败"; exit 1; }
  echo "[index] 补权重索引（transformers 5.x 必需）"
  $PY "$ROOT/cloud/gen_shard_index.py" "$MERGED"
  echo "[free] 释放 base（转 .ninfer 需要 ~11G 空间）"
  rm -rf "$BASE" && echo "[free] base 已删"
  df -h /root/autodl-tmp | tail -1
  ;;

convert)
  mkdir -p "$NINFER_DIR"
  cd "$ROOT/ninfer-master"
  # 纯文本：merged-v61/merged-gen2 无 mtp/visual 张量（见 notes §6），故 --components text
  $PY -m tools.convert \
    --model "$MERGED" --recipe qwen3_8_27b --components text \
    --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
    --name qwen3.8-27b-kittyrev-gen2 --device cpu --out "$NINFER" 2>&1 | tail -25
  echo "[inspect]"
  $PY -m tools.artifact.inspect "$NINFER" 2>&1 | head -14
  ls -lh "$NINFER"
  ;;

*) echo "用法: bash gen2_finish.sh check|merge <adapter_dir>|convert"; exit 1 ;;
esac
