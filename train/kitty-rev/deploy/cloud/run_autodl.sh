#!/usr/bin/env bash
# run_autodl.sh —— AutoDL RTX 4090 24G / PyTorch 2.5.1 / CUDA 12.4 / 数据盘 150G 专用一条龙
# 用法（在实例里执行）：
#   cd /root/autodl-tmp/kitty-rev && bash cloud/run_autodl.sh setup
#   bash cloud/run_autodl.sh smoke     # 拉基座 + 数据体检 + 100 步（约 40 分钟）
#   bash cloud/run_autodl.sh full      # 3 epoch（约 6-10 小时）
#   bash cloud/run_autodl.sh merge     # 合并 + 转 .ninfer + 结构自检（约 50 分钟）
set -euo pipefail

MODE=${1:-setup}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
PY=${PY:-python}
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export HF_HOME=${HF_HOME:-/root/autodl-tmp/hf}
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True

DATA=$ROOT/kitty-rev/data/large-mix/train.jsonl
EVAL=$ROOT/kitty-rev/data/large-mix/eval.jsonl
BASE=$ROOT/base/Qwen3.8-27B
ADAPTER=$ROOT/out/adapter
MERGED=$ROOT/merged/Qwen3.8-27B-kittyrev
NINFER=$ROOT/ninfer/qwen3_8_27b_kittyrev.ninfer

show() { echo; echo "== $* =="; }

case "$MODE" in
setup)
  show "补装训练栈（镜像自带 torch，不重装）"
  $PY -m pip install -q -U "transformers>=5.8" peft trl accelerate datasets bitsandbytes sentencepiece protobuf
  show "环境自检"
  $PY - <<'EOF'
import torch, transformers, peft, trl, datasets, bitsandbytes
cap = torch.cuda.get_device_capability(0)
total = torch.cuda.get_device_properties(0).total_memory/2**30
print(f"torch {torch.__version__} cuda {torch.version.cuda} cap {cap} vram {total:.1f} GiB")
print(f"transformers {transformers.__version__} peft {peft.__version__} trl {trl.__version__} bnb {bitsandbytes.__version__}")
assert total > 22, f"显存 {total:.1f} GiB 不足 22"
EOF
  show "磁盘"
  df -h /root/autodl-tmp | tail -1
  echo "SETUP_OK"
  ;;

smoke|full)
  show "磁盘检查（需 ≥150G 可用）"
  df -h /root/autodl-tmp | tail -1
  show "下载基座（curl 直连 hf-mirror，不产生 HF 缓存副本）"
  if [ ! -f "$BASE/config.json" ]; then
    $PY "$ROOT/scripts/dl_base_curl.py" --repo Qwen/Qwen3.8-27B --dest "$BASE"
  else
    echo "[base] 已存在"
  fi
  show "数据体检"
  $PY "$ROOT/kitty-rev/scripts/validate_dataset.py" --dir "$ROOT/kitty-rev/data/large-mix" --ctx 2048 | tail -3
  show "训练 ($MODE)"
  if [ "$MODE" = smoke ]; then EXTRA="--max-steps 100"; LOG=$ROOT/smoke.log; else EXTRA="--epochs 3"; LOG=$ROOT/full.log; fi
  # --skip-kbit-prepare 在 24 GB 卡上是必须项：peft 默认把全部 requires_grad 参数 upcast fp32，
  # 27B 的 embed/lm_head 一次性要 4.74 GiB，实测 residue 只剩 4.06 GiB → CUDA OOM。
  # 该开关改为冻结主干 + 手动非重入梯度检查点，显存落 20.2/23.5 GiB。
  $PY -u "$ROOT/kitty-rev/scripts/train_kitty.py" --size 27b --ctx 2048 --bs 1 --ga 16 \
     --data "$DATA" --eval-data "$EVAL" --out "$ROOT/out" --all-gpu --skip-kbit-prepare $EXTRA 2>&1 | tee "$LOG"
  echo "DONE: $MODE (log: $LOG)"
  ;;

merge)
  show "合并（CPU，约 30-40 分钟）"
  $PY "$ROOT/scripts/merge.py" --size 27b --adapter "$ADAPTER" --dest "$MERGED"
  show "转 .ninfer（CPU，约 5 分钟）"
  ( cd "$ROOT/ninfer-master" && $PY -m tools.convert \
      --model "$MERGED" --recipe qwen3_8_27b --components text,mtp \
      --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
      --name qwen3.8-27b-kittyrev --device cpu --out "$NINFER" )
  show "结构自检"
  ( cd "$ROOT/ninfer-master" && $PY -m tools.artifact.inspect "$NINFER" | head -12 )
  ls -lh "$NINFER"
  echo "DONE: merge"
  ;;

*) echo "用法: bash cloud/run_autodl.sh setup|smoke|full|merge"; exit 1 ;;
esac
