#!/usr/bin/env bash
# run_after_expand.sh —— 训练完成后「扩容 → 一键产出两个交付物」
#
# 前置：数据盘已扩到 200 G，full 3 epoch 已结束，out/adapter 存在
# 用法：
#   bash cloud/run_after_expand.sh check      # 只体检，不动任何东西
#   bash cloud/run_after_expand.sh all        # 全链路（每步失败即停）
#   bash cloud/run_after_expand.sh merge|gguf|quant|ninfer|act|layers|pack   # 单步
#
# 产出：
#   merged/Qwen3.8-27B-kittyrev/           HF 合并模型 54 G
#   gguf/qwen38_27b_kittyrev_bf16.gguf     GGUF bf16 54 G（可删）
#   gguf/qwen38_27b_kittyrev_iq2s.gguf     GGUF IQ2_S ≈10 G
#   ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer  ★交付物① ≈10 G
#   merged-layers/layer_48..63 + head      ★交付物② 的一部分
#   act-cache/                              ★交付物② 的一部分 7.8 G
#   kittyrev-local-pack.tar                ★交付物② 13.4 G
set -euo pipefail

ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
PY=${PY:-/root/miniconda3/bin/python}
BASE=$ROOT/base/Qwen3.8-27B
ADAPTER=$ROOT/out/adapter
MERGED=$ROOT/merged/Qwen3.8-27B-kittyrev
LC=${LC:-/tmp/lc}
GGUF=$ROOT/gguf
NINFER=$ROOT/ninfer
LAYERS=$ROOT/merged-layers
ACT=$ROOT/act-cache
DATA=$ROOT/kitty-rev/data/large-mix/train.jsonl
LOG=$ROOT/logs/after-expand.log
mkdir -p "$ROOT/logs"
say() { echo; echo "===== [$(date +%H:%M:%S)] $* =====" | tee -a "$LOG"; }
dfv() { df -h "$ROOT" | tail -1 | awk '{print $4}'; }
need_g() {  # need_g <GB> <说明>
  local free_k; free_k=$(df -k "$ROOT" | tail -1 | awk '{print $4}')
  local need_k=$(( $1 * 1024 * 1024 ))
  local free_g=$(( free_k / 1024 / 1024 ))
  echo "[disk] 需要 ${1}G，当前可用 ${free_g}G"
  if [ "$free_k" -lt "$need_k" ]; then echo "[FATAL] 磁盘不足：$2"; return 1; fi
}

case "${1:-check}" in

check)
  say "体检"
  echo "root      = $ROOT"
  df -h "$ROOT" | tail -2
  echo "base      = $([ -d "$BASE" ] && du -sh "$BASE" | cut -f1 || echo MISSING)"
  echo "adapter   = $([ -f "$ADAPTER/adapter_config.json" ] && du -sh "$ADAPTER" | cut -f1 || echo MISSING)"
  echo "merged    = $([ -d "$MERGED" ] && du -sh "$MERGED" | cut -f1 || echo MISSING)"
  echo "llama.cpp = $([ -f "$LC/convert_hf_to_gguf.py" ] && echo OK || echo MISSING)"
  echo "cmake     = $(cmake --version 2>/dev/null | head -1 || echo MISSING)"
  echo "gcc       = $(gcc --version 2>/dev/null | head -1 || echo MISSING)"
  echo "train_kitty 进程 = $(pgrep -c -f train_kitty 2>/dev/null || echo 0)（必须为 0）"
  echo "GPU = $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo n/a)"
  ;;

merge)
  say "① merge（base + adapter → merged）"
  [ -f "$ADAPTER/adapter_config.json" ] || { echo "[FATAL] adapter 缺失"; exit 1; }
  need_g 56 "merge 需 merged 54G"
  if [ -f "$MERGED/config.json" ]; then echo "[skip] merged 已存在"; else
    $PY "$ROOT/scripts/merge.py" --size 27b --adapter "$ADAPTER" --dest "$MERGED"
  fi
  du -sh "$MERGED"; echo "free=$(dfv)"
  ;;

gguf)
  say "② convert_hf_to_gguf（merged → GGUF bf16 54G）"
  need_g 56 "GGUF bf16 需 54G"
  mkdir -p "$GGUF"
  OMP_NUM_THREADS=16 nice -n 10 $PY "$LC/convert_hf_to_gguf.py" "$MERGED" \
      --outfile "$GGUF/qwen38_27b_kittyrev_bf16.gguf" --outtype bf16
  ls -lh "$GGUF"/*.gguf; echo "free=$(dfv)"
  ;;

quant)
  say "③ 编译 llama-quantize（若无）"
  if [ ! -x "$LC/build/bin/llama-quantize" ]; then
    cmake -S "$LC" -B "$LC/build" -DLLAMA_CURL=OFF -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$LC/build" --target llama-quantize -j 16 2>&1 | tail -5
  fi
  ls -l "$LC/build/bin/llama-quantize"
  say "③ llama-quantize → IQ2_S"
  [ -f "$GGUF/qwen38_27b_kittyrev_bf16.gguf" ] || { echo "[FATAL] 缺 bf16 GGUF"; exit 1; }
  need_g 12 "IQ2_S 输出 10G"
  "$LC/build/bin/llama-quantize" "$GGUF/qwen38_27b_kittyrev_bf16.gguf" \
      "$GGUF/qwen38_27b_kittyrev_iq2s.gguf" IQ2_S 16 2>&1 | tail -6
  ls -lh "$GGUF"/qwen38_27b_kittyrev_iq2s.gguf; echo "free=$(dfv)"
  ;;

ninfer)
  say "④ tools.convert（GGUF IQ2_S → .ninfer）★交付物①"
  [ -f "$GGUF/qwen38_27b_kittyrev_iq2s.gguf" ] || { echo "[FATAL] 缺 IQ2_S GGUF"; exit 1; }
  mkdir -p "$NINFER"
  need_g 14 ".ninfer 输出 10G"
  ( cd "$ROOT/ninfer-master" && $PY -m tools.convert \
      --recipe qwen3_8_27b_gguf \
      --source gguf="$GGUF/qwen38_27b_kittyrev_iq2s.gguf" \
      --name qwen3.8-27b-kittyrev-iq2s \
      --out "$NINFER/qwen3_8_27b_kittyrev_iq2s.ninfer" )
  ls -lh "$NINFER"/*.ninfer
  ( cd "$ROOT/ninfer-master" && $PY -m tools.artifact.inspect "$NINFER/qwen3_8_27b_kittyrev_iq2s.ninfer" | head -12 )
  echo "free=$(dfv)"
  ;;

act)
  say "⑤ act-cache（前 48 层激活）★交付物②"
  need_g 10 "act-cache 7.8G"
  $PY "$ROOT/kitty-rev/scripts/precompute_activations.py" \
      --model "$MERGED" --cut 48 --data "$DATA" --ctx 512 --out "$ACT"
  du -sh "$ACT"; ls "$ACT" | wc -l; echo "free=$(dfv)"
  ;;

layers)
  say "⑥ 拆层（只要 layer_48..63 + head）★交付物②"
  need_g 16 "16 层 + head ≈ 15G"
  $PY "$ROOT/kitty-rev/scripts/split_model_layers.py" \
      --src "$MERGED" --out "$LAYERS"
  ls -lh "$LAYERS"/layer_4*.safetensors "$LAYERS"/layer_5*.safetensors "$LAYERS"/layer_6*.safetensors "$LAYERS"/head.safetensors | tail -20
  echo "free=$(dfv)"
  ;;

pack)
  say "⑦ 打包回传"
  need_g 15 "tar 13.4G"
  ( cd "$ROOT" && tar -cf kittyrev-local-pack.tar \
      merged-layers/layer_4[89].safetensors merged-layers/layer_5*.safetensors \
      merged-layers/layer_6*.safetensors merged-layers/head.safetensors \
      merged-layers/layers_index.json act-cache )
  ls -lh "$ROOT/kittyrev-local-pack.tar"
  echo "tar 内文件数（应为 16 层 + head + index + 3908 act）:"
  tar -tf "$ROOT/kittyrev-local-pack.tar" | wc -l
  echo "free=$(dfv)"
  ;;

all)
  say "全链路开始"
  bash "$0" check
  bash "$0" merge
  bash "$0" gguf
  bash "$0" quant
  bash "$0" ninfer
  say "删除 bf16 GGUF 回收 54G"
  rm -f "$GGUF/qwen38_27b_kittyrev_bf16.gguf"
  echo "free=$(dfv)"
  bash "$0" act
  bash "$0" layers
  bash "$0" pack
  say "全链路完成"
  df -h "$ROOT" | tail -1
  ;;

*) echo "用法: bash cloud/run_after_expand.sh check|all|merge|gguf|quant|ninfer|act|layers|pack"; exit 1 ;;
esac
