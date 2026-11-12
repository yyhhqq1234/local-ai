#!/usr/bin/env bash
# gen2_a800.sh —— A800-80G 上 2 小时窗口内的 gen2 训练（pristine 基座 + v2 数据）
#
# 与旧 gen2_train.sh 的区别（旧版有两个致命项，见 run-notes §13）：
#   1) BASE 不再用 merged-v61（那套权重是废的，训练第 1 步 loss 就是 12.43 = 均匀分布）
#      → 用 pristine base/Qwen3.8-27B
#   2) DATA 用 v2（46281 条，kitty 5 类标注齐、门控 13982/13982），不用旧的 46572 条
#
# 用法：bash cloud/gen2_a800.sh pre|smoke|full
set -uo pipefail
MODE=${1:-pre}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
DATA=$KDIR/data/gen2/gen2-nsfw-kitty-v2.jsonl
OUT=$ROOT/out/gen2-a800
LOG=$ROOT/gen2-a800-$MODE.log
PY=${PY:-/root/miniconda3/bin/python}

case "$MODE" in
pre)
  echo "=== 环境 ==="
  $PY - <<'PYEOF'
import torch, transformers, peft, trl, bitsandbytes as bnb
p = torch.cuda.get_device_properties(0)
print(f"torch {torch.__version__} cuda {torch.version.cuda}")
print(f"transformers {transformers.__version__} peft {peft.__version__} trl {trl.__version__} bnb {bnb.__version__}")
print(f"gpu {p.name} vram {p.total_memory/2**30:.1f} GiB")
PYEOF
  echo "=== 基座 ==="
  ls "$BASE/config.json" 2>/dev/null || echo "MISSING base"
  N=$(ls "$BASE"/*.safetensors 2>/dev/null | wc -l); echo "safetensors 片数 = $N （要 18）"
  du -sh "$BASE" 2>/dev/null
  echo "=== 数据 ==="
  wc -l "$DATA" 2>/dev/null || echo "MISSING data"
  echo "=== 磁盘 ==="
  df -h /root/autodl-tmp | tail -1
  ;;

smoke|full)
  [ -f "$BASE/config.json" ] || { echo "[FATAL] 缺基座"; exit 1; }
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  case "$MODE" in
    smoke) EXTRA="--max-steps 20 --save-steps 0" ;;
    full)  EXTRA="--max-steps ${STEPS:-320} --save-steps ${SAVE:-160}" ;;
  esac
  echo "[run] $MODE base=$BASE steps=$EXTRA"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT" \
    --ctx ${CTX:-2048} --bs 1 --ga ${GA:-16} --lr ${LR:-6e-5} \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare $EXTRA 2>&1 | tee "$LOG"
  echo "DONE: $MODE  log=$LOG"
  ;;

*) echo "用法: bash cloud/gen2_a800.sh pre|smoke|full"; exit 1 ;;
esac
