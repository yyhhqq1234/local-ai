#!/bin/bash
# quant_gen2_noimx.sh —— 定因 A/B：去掉 --imatrix 重跑 IQ2_S（其余配方与 quant_gen2.sh 完全一致）
# 目的：区分「imatrix-v4r.dat 与 gen2 失配」与「merge 权重本身有问题」
set -u
R=/root/autodl-tmp/kitty-rev
BIN=/root/autodl-tmp/lc/build-cuda89/bin
SRC=$R/gguf/gen2-bf16.gguf
DST=$R/gguf/gen2-iq2s-noimx.gguf
LOG=$R/logs/gen2-quant-noimx.log

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

echo "[Q-noimx] src=$SRC  $(stat -c %s "$SRC" 2>/dev/null) B"
echo "[Q-noimx] 无 imatrix（对照 A 组）"
"$BIN/llama-quantize" "${TT[@]}" "$SRC" "$DST" IQ2_S 64 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
echo "[Q-noimx] rc=$rc size=$(stat -c %s "$DST" 2>/dev/null)"
exit $rc
