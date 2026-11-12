#!/usr/bin/env bash
# gen3_1_5090.sh —— P0 复训：统一门控口径（system 单开关），从 gen3 adapter-2800 续训 600 步
#
# 依据：train/logs/gen3-acceptance-20261030.md §2「门控对系统消息失灵、对前缀有效」
#       gen3 数据把开关写在两处（user 前缀 4,953 / system 2,086），步数放大后前缀压过 system。
#       gen3.1 把全部 gate 行的开关统一到 system（build_gen3_1.py），再从 2800 档 adapter 续训，
#       预期：给 system 说就认，不再依赖 [[NSFW]] 前缀。
#
# 用法：bash gen3_1_5090.sh pre|train
set -uo pipefail
MODE=${1:-pre}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
DATA=$KDIR/data/gen2/gen3_1-nsfw-kitty.jsonl
INIT=${INIT:-$ROOT/init/gen3-adapter-2800}
OUT=$ROOT/out/gen3_1
LOG=$ROOT/gen3_1-5090-$MODE.log
PY=${PY:-/root/miniconda3/bin/python}
BS=${BS:-2}; GA=${GA:-8}; CTX=${CTX:-2048}; LR=${LR:-3e-5}; STEPS=${STEPS:-600}; SAVE=${SAVE:-200}

case "$MODE" in
pre)
  echo "=== 环境 ==="
  $PY - <<'PYEOF'
import warnings; warnings.filterwarnings("ignore")
import torch, transformers, trl, triton
p = torch.cuda.get_device_properties(0)
print(f"torch {torch.__version__} cuda {torch.version.cuda} cap {torch.cuda.get_device_capability(0)}")
print(f"transformers {transformers.__version__} trl {trl.__version__} triton {triton.__version__}")
x = torch.randn(256, 256, device="cuda"); y = x @ x; torch.cuda.synchronize()
print(f"MATMUL OK {float(y.sum()):.3f}")
PYEOF
  echo "=== 数据/续训源 ==="
  wc -l "$DATA" 2>/dev/null || echo "MISSING data $DATA"
  ls -la "$INIT/adapter_model.safetensors" 2>/dev/null || echo "MISSING init adapter $INIT"
  echo "=== 磁盘 ==="
  df -h /root/autodl-tmp | tail -1
  ;;

train)
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  [ -f "$INIT/adapter_model.safetensors" ] || { echo "[FATAL] 缺续训源 $INIT"; exit 1; }
  echo "[run] steps=$STEPS bs=$BS ga=$GA lr=$LR init=$INIT"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT" \
    --init-adapter "$INIT" \
    --ctx $CTX --bs $BS --ga $GA --lr $LR \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare \
    --max-steps $STEPS --save-steps $SAVE 2>&1 | tee "$LOG"
  echo "DONE train log=$LOG"
  ;;

*) echo "用法: bash gen3_1_5090.sh pre|train"; exit 1 ;;
esac
