#!/usr/bin/env bash
# gen3_5090.sh —— GEN3 训练入口（RTX 5090 32G / torch cu128 sm_120）
#
# 相对 gen2_a800.sh 的改动
#   1 torch 必须是 cu128（2.6.0+cu124 在 sm_120 上 "no kernel image is available"，实测）
#   2 数据换 GEN3（47,105 条：v2 46,281 + re-qc silver 净增 824）
#   3 bs2/ga8（等效 16），OOM 时由 chain 回落 bs1/ga16
#   4 27B 4bit QLoRA 在 32G 上不加 offload，靠 --all-gpu 全放 0 卡
#
# 用法：bash gen3_5090.sh pre|smoke|gate|full
set -uo pipefail
MODE=${1:-pre}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
DATA=$KDIR/data/gen2/gen3-nsfw-kitty.jsonl
OUT=$ROOT/out/gen3
LOG=$ROOT/gen3-5090-$MODE.log
PY=${PY:-/root/miniconda3/bin/python}
BS=${BS:-2}
GA=${GA:-8}
CTX=${CTX:-2048}
LR=${LR:-6e-5}

case "$MODE" in
pre)
  echo "=== 环境 ==="
  $PY - <<'PYEOF'
import warnings; warnings.filterwarnings("ignore")
import torch, transformers, peft, trl
p = torch.cuda.get_device_properties(0)
print(f"torch {torch.__version__} cuda {torch.version.cuda} cap {torch.cuda.get_device_capability(0)}")
print(f"transformers {transformers.__version__} peft {peft.__version__} trl {trl.__version__}")
print(f"gpu {p.name} vram {p.total_memory/2**30:.1f} GiB sm_{p.major}{p.minor}")
try:
    import bitsandbytes as bnb
    print(f"bnb {bnb.__version__}")
except Exception as e:
    print(f"bnb MISSING {type(e).__name__}")
x = torch.randn(256, 256, device="cuda"); y = x @ x; torch.cuda.synchronize()
print(f"MATMUL OK sum={y.sum().item():.3f}")
PYEOF
  echo "=== 基座 ==="
  ls "$BASE/config.json" >/dev/null 2>&1 || echo "MISSING base"
  echo "safetensors 片数 = $(ls "$BASE"/*.safetensors 2>/dev/null | wc -l) （要 18）"
  du -sh "$BASE" 2>/dev/null
  echo "=== 数据 ==="
  wc -l "$DATA" 2>/dev/null || echo "MISSING data"
  echo "=== 磁盘 ==="
  df -h /root/autodl-tmp | tail -1
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
  ;;

gate)
  echo "=== gate1：基座 LM loss（0<loss<6；≈12 = 均匀分布 = 废权重）==="
  $PY "$ROOT/cloud/hf_lm_loss.py" "$BASE" 2 2>&1 | tee "$LOG" | tail -6
  LOSS=$(grep -oE 'loss=[0-9.]+' "$LOG" | head -1 | cut -d= -f2); LOSS=${LOSS:-99}
  echo "gate1 loss=$LOSS"
  $PY -c "import sys;v=float('$LOSS');sys.exit(0 if 0<v<6 else 1)" && echo "GATE PASS" || { echo "GATE FAIL"; exit 12; }
  ;;

smoke)
  [ -f "$BASE/config.json" ] || { echo "[FATAL] 缺基座"; exit 1; }
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  echo "[run] smoke bs=$BS ga=$GA steps=20"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT-smoke" \
    --ctx $CTX --bs $BS --ga $GA --lr $LR \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare \
    --max-steps 20 --save-steps 0 2>&1 | tee "$LOG"
  echo "DONE smoke log=$LOG"
  ;;

full)
  [ -f "$BASE/config.json" ] || { echo "[FATAL] 缺基座"; exit 1; }
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  STEPS=${STEPS:-2800}
  SAVE=${SAVE:-400}
  echo "[run] full bs=$BS ga=$GA steps=$STEPS save=$SAVE"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT" \
    --ctx $CTX --bs $BS --ga $GA --lr $LR \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare \
    --max-steps $STEPS --save-steps $SAVE 2>&1 | tee "$LOG"
  echo "DONE full log=$LOG"
  ;;

*) echo "用法: bash gen3_5090.sh pre|smoke|gate|full"; exit 1 ;;
esac
