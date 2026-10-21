#!/usr/bin/env bash
# setup.sh —— 云端 24GB 卡环境初始化（Ubuntu 22.04 + CUDA 12.x 镜像）
# 用法：bash setup.sh            # 默认 cu121
#       TORCH_INDEX=https://download.pytorch.org/whl/cu124 bash setup.sh
set -euo pipefail

PY=${PY:-python3}
TORCH_INDEX=${TORCH_INDEX:-https://download.pytorch.org/whl/cu121}
WORK=${WORK:-$HOME/kitty-rev}

echo "== [1/4] python / pip =="
$PY -V
$PY -m pip install -U pip setuptools wheel

echo "== [2/4] torch (cu121) =="
$PY -m pip install torch torchvision --index-url "$TORCH_INDEX"

echo "== [3/4] 训练栈 =="
$PY -m pip install "transformers>=5.8" peft trl accelerate datasets bitsandbytes sentencepiece protobuf

echo "== [4/4] 自检 =="
$PY - <<'EOF'
import torch, transformers, peft, trl, datasets, bitsandbytes
cap = torch.cuda.get_device_capability(0) if torch.cuda.is_available() else None
total = torch.cuda.get_device_properties(0).total_memory/2**30 if torch.cuda.is_available() else 0
print("torch", torch.__version__, "cuda", torch.version.cuda, "cap", cap, f"vram {total:.1f} GiB")
print("transformers", transformers.__version__, "peft", peft.__version__, "trl", trl.__version__, "bnb", bitsandbytes.__version__)
assert torch.cuda.is_available(), "CUDA 不可用：换带 GPU 的镜像"
assert total > 20, f"显存 {total:.1f} GiB < 20 GiB：本脚本面向 24GB 卡"
print("SETUP_OK")
EOF

mkdir -p "$WORK"
echo "环境就绪：$WORK（把 bundle 解到这个目录即可）"
