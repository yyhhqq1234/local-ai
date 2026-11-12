#!/usr/bin/env bash
# run_all.sh —— 云端一条龙：拉基座 → 数据体检 → 训练 → 合并 → 转 .ninfer → 结构自检
# 用法：
#   bash run_all.sh smoke      # 100 步冒烟（先验证链路，约 20-40 分钟）
#   bash run_all.sh full       # 正式训练（3 epoch，约 6-10 小时 / 4090）
#   bash run_all.sh merge      # 只做合并+转换（adapter 已有）
set -euo pipefail

MODE=${1:-smoke}
ROOT=${ROOT:-$HOME/kitty-rev}
PY=${PY:-python3}
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export HF_HOME=${HF_HOME:-$ROOT/hf}
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True

cd "$ROOT"
DATA=${DATA:-$ROOT/kitty-rev/data/large-mix/train.jsonl}
EVAL=${EVAL:-$ROOT/kitty-rev/data/large-mix/eval.jsonl}
BASE=${BASE:-$ROOT/base/Qwen3.8-27B}
ADAPTER=${ADAPTER:-$ROOT/out/adapter}
MERGED=${MERGED:-$ROOT/merged/Qwen3.8-27B-kittyrev}
NINFER=${NINFER:-$ROOT/ninfer/qwen3_8_27b_kittyrev.ninfer}

fetch_base() {
  if [ -f "$BASE/config.json" ]; then echo "[base] 已存在，跳过"; return; fi
  echo "[base] 拉取 Qwen/Qwen3.8-27B（≈52 GiB，云端带宽通常 200-500 MiB/s）"
  "$PY" - <<'EOF'
import os
from huggingface_hub import snapshot_download
p = snapshot_download(
    repo_id="Qwen/Qwen3.8-27B",
    local_dir=os.path.join(os.path.expanduser("~"), "kitty-rev", "base", "Qwen3.8-27B"),
    allow_patterns=["*.json", "*.safetensors", "*.model", "*.jinja", "*.txt"],
    max_workers=8,
)
print("[base] done", p)
EOF
}

check_data() {
  "$PY" kitty-rev/scripts/validate_dataset.py --dir kitty-rev/data/large-mix --ctx 2048 | tail -3
}

train() {
  local extra=$1
  echo "[train] $MODE  ($extra)"
  "$PY" kitty-rev/scripts/train_kitty.py \
    --size 27b --ctx 2048 --bs 1 --ga 16 \
    --data "$DATA" --eval-data "$EVAL" --out "$ROOT/out" \
    --all-gpu $extra
}

merge_and_convert() {
  echo "[merge] adapter → merged（CPU，54 GiB，20-40 分钟）"
  "$PY" scripts/merge.py --size 27b --adapter "$ADAPTER" --dest "$MERGED"

  echo "[convert] merged → .ninfer（CPU，约 2-5 分钟）"
  if [ ! -d "$ROOT/ninfer-master" ]; then
    echo "[convert] 缺 ninfer-master；把本地 train/lines/_shared/tools/ninfer-master 一起上传到 $ROOT"
    exit 2
  fi
  ( cd "$ROOT/ninfer-master" && "$PY" -m tools.convert \
      --model "$MERGED" --recipe qwen3_8_27b --components text,mtp \
      --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
      --name qwen3.8-27b-kittyrev --device cpu --out "$NINFER" )

  echo "[verify] 结构自检"
  ( cd "$ROOT/ninfer-master" && "$PY" -m tools.artifact.inspect "$NINFER" | head -14 )
}

case "$MODE" in
  smoke) fetch_base; check_data; train "--max-steps 100" ;;
  full)  fetch_base; check_data; train "--epochs 3" ;;
  merge) merge_and_convert ;;
  *) echo "用法: bash run_all.sh smoke|full|merge"; exit 1 ;;
esac

echo "DONE: $MODE"
