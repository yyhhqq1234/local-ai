#!/usr/bin/env bash
# gen2_train.sh —— 第 2 代：在 v6/v6.1 线上续训 NSFW 门控 + kitty 工作台数据（27B QLoRA，4090 24G）
#
# 起点选择（时间/磁盘约束下的实测结论）：
#   base/Qwen3.8-27B 已被云端删除；hf-mirror 单连接 3 MB/s、aria2 x16 仅 8 MB/s（xet-bridge 限速）
#   → 51.77 GiB 要 2h+，4h 预算里不可接受。
#   改用 merged-v61（bf16 全量 27B = base + v61 adapter，已含 v6 线全部改动）当基座：
#   v6 = merged-v5 + out-v6/v6 adapter；v61 = merged-v61(base-v61b + out-v61) → 含 v6 线
#   在 merged-v61 上挂新 LoRA（不 --init-adapter，避免二次叠加 v6 权重）= 血统文档里的 B 路线
#
# 数据：/root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen2-nsfw-kitty.jsonl
#       46572 条 / 27.3 M token（nsfw-gated 22180 + kitty-v3 23292 + 抗遗忘 1100）
# 产物：/root/autodl-tmp/kitty-rev/kitty-rev/out/gen2-nsfw/adapter
#
# 用法：
#   bash gen2_train.sh pre      # 环境/基座/数据体检
#   bash gen2_train.sh smoke    # 30 步冒烟
#   bash gen2_train.sh full     # 正式 2 epoch
#   bash gen2_train.sh resume   # 从 checkpoint 续
set -uo pipefail

MODE=${1:-pre}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
DATA=$KDIR/data/gen2/gen2-nsfw-kitty.jsonl
BASE=$ROOT/merged-v61
OUT=$KDIR/out/gen2-nsfw
LOG=$ROOT/gen2-$MODE.log

PY=${PY:-/root/miniconda3/bin/python}

case "$MODE" in
pre)
  $PY - <<'PYEOF'
import torch, transformers, peft, trl
p = torch.cuda.get_device_properties(0)
print(f"torch {torch.__version__} cuda {torch.version.cuda}")
print(f"transformers {transformers.__version__} peft {peft.__version__} trl {trl.__version__}")
print(f"gpu {p.name} vram {p.total_memory/2**30:.1f} GiB")
PYEOF
  echo "--- base ---";  ls "$BASE/config.json" 2>/dev/null || echo "MISSING base: $BASE"
  echo "--- data ---";  ls -l "$DATA" 2>/dev/null || echo "MISSING data: $DATA"
  echo "--- disk ---";  df -h /root/autodl-tmp | tail -1
  ;;

smoke|full|resume)
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  [ -f "$BASE/config.json" ] || { echo "[FATAL] 缺基座 $BASE"; exit 1; }
  case "$MODE" in
    smoke)  EXTRA="--max-steps 30 --save-steps 0" ;;
    full)   EXTRA="--max-steps 500 --save-steps 50" ;;
    resume) EXTRA="--epochs 2 --save-steps 200 --resume $OUT" ;;
  esac
  echo "[run] $MODE base=$BASE"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT" \
    --ctx 2048 --bs 1 --ga 16 --lr 6e-5 \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare --allow-partial-cats $EXTRA 2>&1 | tee "$LOG"
  echo "DONE: $MODE  log=$LOG"
  ;;

*) echo "用法: bash gen2_train.sh pre|smoke|full|resume"; exit 1 ;;
esac
