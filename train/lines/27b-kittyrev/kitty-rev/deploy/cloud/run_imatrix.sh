#!/bin/bash
# run_imatrix.sh —— 用 gen2 自己的 bf16 gguf + 训练集抽样校准文本算重要性矩阵
# -ngl 24：24 GB 卡放 24 层（约 18 GB），其余层留 CPU；-ngl 99 会 cudaMalloc 48 GB 直接 OOM（已实测）
set -u
R=/root/autodl-tmp/kitty-rev
BIN=/root/autodl-tmp/lc/build-cuda89/bin
cd "$R"
echo "[imx] start $(date '+%F %T')"
"$BIN/llama-imatrix" -m gguf/gen2-bf16.gguf -f gguf/calib-gen2.txt \
  -o imatrix-gen2.dat --output-format dat \
  --chunks 120 -t 48 -ngl 24 -c 512
rc=$?
echo "[imx] rc=$rc size=$(stat -c %s imatrix-gen2.dat 2>/dev/null)"
exit $rc
