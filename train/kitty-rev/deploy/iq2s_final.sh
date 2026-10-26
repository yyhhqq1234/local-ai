#!/usr/bin/env bash
# iq2s_final.sh —— merged-flat → bf16 GGUF → IQ2_S（保 ssm_alpha/beta 为 q8_0）→ .ninfer
# 目标：产出 <10 G 的 .ninfer，5070 Ti（12 G 显存）可跑
set -euo pipefail
R=/root/autodl-tmp/kitty-rev
VERIFY=$R/kitty-rev/scripts/verify_expand.py
PIN=$R/kitty-rev/scripts/pin_arch.py
PY=/root/miniconda3/bin/python
LC=/tmp/lc
say() { echo; echo "===== [$(date +%H:%M:%S)] $* ====="; }
dfv() { df -h "$R" | tail -1 | awk '{print $4}'; }
needg() { local need=$1; local avail=$(df --output=avail -BG "$R" | tail -1 | tr -dc '0-9'); \
  [ "$avail" -ge "$need" ] || { echo "[FATAL] 需要 ${need}G，只有 ${avail}G"; exit 1; }; echo "[disk] ${avail}G ✓"; }

say "① pin architectures（convert 前的硬前置，坑 c）"
if [ ! -f "$PIN" ]; then echo "[FATAL] 缺 $PIN"; exit 1; fi
"$PY" "$PIN" --dir "$R/merged-flat" --index || { echo "[FATAL] pin_arch 失败"; exit 1; }

say "① merged-flat → bf16 GGUF"
needg 60
cd "$LC"
"$PY" convert_hf_to_gguf.py "$R/merged-flat" --outfile "$R/gguf/bf16.gguf" --outtype bf16 2>&1 | tail -2
ls -lh "$R/gguf/bf16.gguf" | awk '{print "  bf16:", $5}'
echo "free=$(dfv)"

say "② tensor-type 逐条（保 ssm_alpha/beta 为 q8_0）"
# 雷区：--tensor-type-file 实测失败（README/踩坑已经把「逐条 --tensor-type」定为唯一可行路）
TT=()
for i in $(seq 0 63); do
  TT+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0")
  TT+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0")
done
echo "[tt] ${#TT[@]} 个参数（64 层 × 2）"

say "③ IQ2_S 量化（约 22 min）"
needg 14
"$LC/build/bin/llama-quantize" \
  --imatrix "$R/imatrix.dat" \
  "${TT[@]}" \
  "$R/gguf/bf16.gguf" "$R/gguf/iq2s.gguf" IQ2_S 16 2>&1 | tail -3
ls -lh "$R/gguf/iq2s.gguf" | awk '{print "  iq2s:", $5}'
# 判据：张量数 / 量化型占比 / 有没有退化回 f16（rc=0 不代表格式对）
"$PY" "$VERIFY" --root "$R" --step 3 --quant "$R/gguf/iq2s.gguf" \
  || { echo "[FATAL] IQ2_S 产物特征不合格"; exit 1; }

say "④ 删 bf16 回收空间"
rm -f "$R/gguf/bf16.gguf"
echo "free=$(dfv)"

say "⑤ GGUF → .ninfer（recipe qwen3_8_27b_gguf，字节直通）"
needg 14
cd "$R/ninfer-all-master"
"$PY" -m tools.convert \
  --model "$R/merged-cfg/Qwen3.8-27B-kittyrev" \
  --recipe qwen3_8_27b_gguf \
  --source gguf="$R/gguf/iq2s.gguf" \
  --components text \
  --name qwen3.8-27b-kittyrev-iq2s \
  --out "$R/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer" 2>&1 | tail -4
ls -lh "$R/ninfer/"*.ninfer | awk '{print "  ninfer:", $5, $9}'

say "⑥ inspect 自检（落盘 + 硬判 objects/tensors/formats）"
"$PY" -m tools.artifact.inspect "$R/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer" \
  > "$R/logs/inspect-iq2s.txt" 2>&1
grep -aE 'version|name:|file_bytes|objects|tensors|formats|layouts' \
  "$R/logs/inspect-iq2s.txt" | head -8
"$PY" "$VERIFY" --root "$R" --step 5 --inspect-json "$R/logs/inspect-iq2s.txt" \
  || { echo "[FATAL] .ninfer 产物特征不合格"; exit 1; }

say "完成"
echo "free=$(dfv)"
ls -lh "$R/ninfer/"*.ninfer
