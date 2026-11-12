#!/bin/bash
# quant_gen2.sh —— gen2 bf16 gguf → GSQ-RCO IQ2_S（复用 v6 已验证的 tensor-type 组合）
#
# 来源：logs/v6/quant_v6.sh（GSQ-RCO 配方 = imatrix 引导 + 分张量类型分配）
#   ① 各层 ssm_alpha/ssm_beta → q8_0（SSM 状态张量对低位量化极敏感）
#   ② blk.64.*（MTP 15 张量）→ q8_0；gen2 无 MTP，llama-quantize 会自动忽略不存在的张量
#   ③ 其余按 IQ2_S 默认（mlp → iq2_xs、attn qkv → q4_k，实测 v6 落 iq2_xs 为可接受）
# imatrix：imatrix-v4r.dat（27 MB，27B 校准统计）
set -u
R=/root/autodl-tmp/kitty-rev
BIN=/root/autodl-tmp/lc/build-cuda89/bin
IMX=$R/imatrix-v4r.dat
SRC=$R/gguf/gen2-bf16.gguf
DST=$R/gguf/gen2-iq2s.gguf
LOG=$R/logs/gen2-quant.log

TT=()
for i in $(seq 0 63); do
  TT+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0")
  TT+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0")
done
for n in nextn.eh_proj.weight attn_norm.weight ffn_down.weight ffn_gate.weight ffn_up.weight \
         post_attention_norm.weight attn_k_norm.weight attn_k.weight attn_output.weight \
         attn_q_norm.weight attn_q.weight attn_v.weight nextn.shared_head_norm.weight \
         nextn.enorm.weight nextn.hnorm.weight; do
  TT+=(--tensor-type "blk.64.$n=q8_0")
done

IMXARG=()
if [ -f "$IMX" ]; then IMXARG=(--imatrix "$IMX"); else echo "[WARN] 缺 imatrix"; fi

echo "[Q] src=$SRC $(stat -c %s "$SRC" 2>/dev/null) B"
echo "[Q] tensor-type 条数 = ${#TT[@]}"
"$BIN/llama-quantize" "${IMXARG[@]}" "${TT[@]}" "$SRC" "$DST" IQ2_S 64 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[Q] rc=$rc"
if [ -f "$DST" ]; then
  echo "[Q] size=$(stat -c %s "$DST")  (验收窗口 9.0e9 ~ 10.737e9)"
fi
exit $rc
