#!/usr/bin/env bash
# gen3_1p_5090.sh —— P0′ 复训：单一拒绝句式 + 正负 1:1，从 adapter-600 续训 1500 步
#
# 依据（2026-11-01 实测定位）：
#   L1(2.80 bpw) 与 R(3.01 bpw) 门控 recall 均 0.375、leak 均 0.500 —— 完全相同
#   → 门控失败与量化无关，是训练侧信号强度问题
#   数据侧病灶：旧负样本是多种"闲聊式/教用户开开关"的写法（14,014 条全是变体），
#   模型学到的是"讲道理"而不是"收住口"；正负比 1:2 进一步稀释。
#
# 本轮改动（train/lines/_shared/scripts/build_gen3_1p.py 产出）：
#   · 负样本 14,014 条全部改写为**单一固定拒绝句式**（残留闲聊式 0）
#   · 正样本 ×2 过采样 → pos 13,998 : neg 14,014 = 1 : 1.001
#   · kitty 逆向 + 其他数据原样保留（26,052）
#   · 合计 54,064 行 / 124.4 MiB / sha256 ea84f68585aba590…
#
# 用法（云端）：
#   bash gen3_1p_5090.sh pre      # 环境+数据+续训源 三项自检，不烧机时
#   bash gen3_1p_5090.sh train    # 1500 步
#   STEPS=800 SAVE=200 LR=3e-5 bash gen3_1p_5090.sh train
#
# 前置上传（本机 → 云端，两件）：
#   1  train/lines/27b-kittyrev/data/versions/gen3_1p-nsfw-kitty.20261101-022516.jsonl  (124.4 MiB)
#      → /root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen5-text.jsonl
#   2  train/lines/27b-kittyrev/local-pack/gen3_1/adapter-600/  (159 MB)
#      → /root/autodl-tmp/out/gen3_1p/checkpoint-600/
#      （若云端 out/gen3_1/adapter-600 仍在，可省这次上传，INIT 指过去即可）
set -uo pipefail
MODE=${1:-pre}
ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
KDIR=$ROOT/kitty-rev
BASE=$ROOT/base/Qwen3.8-27B
DATA=${DATA:-$KDIR/data/gen2/gen5-text.jsonl}
INIT=${INIT:-$ROOT/out/gen3_1p/checkpoint-600}
OUT=${OUT:-$ROOT/out/gen5}
LOG=$ROOT/gen5-5090-$MODE.log
PY=${PY:-/root/miniconda3/bin/python}
BS=${BS:-2}; GA=${GA:-8}; CTX=${CTX:-2048}
LR=${LR:-1e-5}; STEPS=${STEPS:-600}; SAVE=${SAVE:-200}
EXPECT_SHA=6c298ab8ecfda793

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
  echo "=== 数据 ==="
  if [ -f "$DATA" ]; then
    wc -l "$DATA"
    echo -n "sha256: "; sha256sum "$DATA" | cut -c1-16
    case "$(sha256sum "$DATA" | cut -c1-16)" in
      "$EXPECT_SHA") echo "  ✔ 与本地一致（P0′ 数据集）" ;;
      *) echo "  ✘ 与期望 $EXPECT_SHA 不符 —— 传错文件了，先换数据" ;;
    esac
    # 负样本口径自查：必须是单一固定句式
    grep -c '当前为常规模式（未授权成人向内容），不输出露骨性描写。' "$DATA" || true
    grep -c '未检测到 NSFW 开关' "$DATA" || echo "  残留闲聊式 0 ✔"
  else
    echo "MISSING data $DATA"
  fi
  echo "=== 续训源 ==="
  ls -la "$INIT/adapter_model.safetensors" 2>/dev/null || echo "MISSING init adapter $INIT"
  echo "=== 磁盘 ==="
  df -h /root/autodl-tmp | tail -1
  echo "=== 显存 ==="
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
  ;;

train)
  [ -f "$DATA" ] || { echo "[FATAL] 缺数据 $DATA"; exit 1; }
  [ -f "$INIT/adapter_model.safetensors" ] || { echo "[FATAL] 缺续训源 $INIT"; exit 1; }
  echo "[run] steps=$STEPS bs=$BS ga=$GA lr=$LR ctx=$CTX init=$INIT"
  echo "[run] data=$(wc -l < "$DATA") 行"
  $PY -u "$KDIR/scripts/train_kitty.py" \
    --size 27b --base "$BASE" --data "$DATA" --out "$OUT" \
    --init-adapter "$INIT" \
    --ctx $CTX --bs $BS --ga $GA --lr $LR \
    --lora-r 16 --lora-alpha 32 \
    --all-gpu --skip-kbit-prepare \
    --max-steps $STEPS --save-steps $SAVE 2>&1 | tee "$LOG"
  echo "DONE train log=$LOG"
  ;;

*) echo "用法: bash gen3_1p_5090.sh pre|train"; exit 1 ;;
esac
