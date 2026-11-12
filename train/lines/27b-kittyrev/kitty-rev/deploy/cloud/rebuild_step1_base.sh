#!/bin/bash
# rebuild_step1_base.sh —— 重建第 1 步：腾空间 + 下 pristine 基座 + 校验
# 判据：18 个 safetensors 片、config.json、index.json；抽样张量 mean|w| ≈ 5e-3~2e-2
set -u
R=/root/autodl-tmp/kitty-rev
BASE=$R/base/Qwen3.8-27B
BIN=/root/autodl-tmp/lc/build-cuda89/bin
LOG=$R/logs/rebuild-base.log

echo "[1] 清理不再需要的中间产物" | tee -a "$LOG"
rm -rf $R/gguf/gen2-bf16.gguf $R/gguf/gen2-iq2s.gguf && echo "[1] 删除 gen2 gguf" | tee -a "$LOG"
df -h /root/autodl-tmp | tail -1 | tee -a "$LOG"

echo "[2] 下载基座（aria2 x16）" | tee -a "$LOG"
/root/miniconda3/bin/python $R/cloud/gen_aria2_list.py --dest "$BASE" --out /root/autodl-tmp/base.aria2.txt | tail -2 | tee -a "$LOG"
aria2c -x16 -s16 -j4 -c --file-allocation=none -i /root/autodl-tmp/base.aria2.txt \
       --summary-interval=120 >> "$LOG" 2>&1
echo "[2] rc=$?  size=$(du -sh $BASE | cut -f1)" | tee -a "$LOG"

echo "[3] 校验" | tee -a "$LOG"
ls "$BASE"/*.safetensors 2>/dev/null | wc -l | xargs -I{} echo "[3] safetensors 片数 = {}"
ls -l "$BASE/config.json" "$BASE/tokenizer.json" 2>/dev/null | tail -2
/root/miniconda3/bin/python $R/cloud/hf_audit.py "$BASE" 5 2>&1 | tail -12 | tee -a "$LOG"
echo "[3] done $(date '+%F %T')" | tee -a "$LOG"
