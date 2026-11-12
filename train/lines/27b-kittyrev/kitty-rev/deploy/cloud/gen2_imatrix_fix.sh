#!/bin/bash
# gen2_imatrix_fix.sh —— 用 gen2 自己的 imatrix 重做 GSQ-RCO IQ2_S（定因 A/B 的最终解）
#
# 依据：本地取证已排除
#   ① 量化配方：gen2 与 v6 逐参数 format 差异 = 0
#   ② 合并：adapter ΔW rms 3e-5（v6 是 3e-4），权重尺度 0.02，delta 仅 0.15% → merge 正常
# 剩下唯一未验证变量 = imatrix（imatrix-v4r.dat 是另一代模型算的，IQ2_XS 会按它选块内尺度）
#
# 用法：bash gen2_imatrix_fix.sh [calib|quant|all]
set -u
R=/root/autodl-tmp/kitty-rev
BIN=/root/autodl-tmp/lc/build-cuda89/bin
SRC=$R/gguf/gen2-bf16.gguf
CAL=$R/gguf/calib-gen2.txt
IMX=$R/imatrix-gen2.dat
DST=$R/gguf/gen2-iq2s-imx2.gguf
MODE=${1:-all}

make_calib() {
  if [ -f "$CAL" ]; then echo "[calib] 已存在 $(stat -c %s "$CAL") B"; return; fi
  /root/miniconda3/bin/python - "$CAL" <<'PY'
import json, sys, random
out = open(sys.argv[1], 'w', encoding='utf-8')
n = 0
random.seed(42)
with open('/root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen2-nsfw-kitty.jsonl', encoding='utf-8') as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        parts = []
        for m in d.get('messages', []):
            c = m.get('content')
            if isinstance(c, str):
                parts.append(c)
        t = '\n'.join(parts)
        if len(t) < 50:
            continue
        out.write(t[:4000] + '\n')
        n += 1
        if n >= 400:
            break
out.close()
print('[calib] samples', n)
PY
  echo "[calib] $(stat -c %s "$CAL") B"
}

run_imatrix() {
  echo "[imatrix] 用 gen2 自己的 bf16 gguf + 训练集抽样算重要性矩阵（CPU，20-40 min）"
  "$BIN/llama-imatrix" -m "$SRC" -f "$CAL" -o "$IMX" --chunks 200 -t 64 -ngl 99 -c 512 2>&1 | tail -20
  echo "[imatrix] $(stat -c %s "$IMX" 2>/dev/null) B"
}

run_quant() {
  TT=()
  for i in $(seq 0 63); do
    TT+=(--tensor-type "blk.$i.ssm_alpha.weight=q8_0")
    TT+=(--tensor-type "blk.$i.ssm_beta.weight=q8_0")
  done
  echo "[quant] 用 gen2 自算 imatrix 重跑 IQ2_S"
  "$BIN/llama-quantize" --imatrix "$IMX" "${TT[@]}" "$SRC" "$DST" IQ2_S 64 2>&1 | tee $R/logs/gen2-quant-imx2.log | tail -5
  echo "[quant] size=$(stat -c %s "$DST" 2>/dev/null)  (目标 <10.737e9)"
}

case "$MODE" in
  calib) make_calib ;;
  quant) run_quant ;;
  all)   make_calib; run_imatrix; run_quant ;;
  *) echo "用法: bash gen2_imatrix_fix.sh [calib|quant|all]"; exit 1 ;;
esac
