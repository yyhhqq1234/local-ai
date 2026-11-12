#!/usr/bin/env bash
# iq2s_fix.sh —— 重跑量化：把 ssm_alpha/ssm_beta 钉在 q8_0（recipe 只接受 BF16/Q8_0），其余同 IQ2_S
set -eu
ROOT=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
LC=/tmp/lc
BF16=$ROOT/gguf/qwen38_kittyrev_bf16.gguf
IQ2S=$ROOT/gguf/qwen38_kittyrev_iq2s_v2.gguf
CONV=$ROOT/ninfer-all-master
OUT=$ROOT/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer

say() { echo "[$(date +%H:%M:%S)] $*"; }
dfv() { df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9'; }

say "start, avail $(dfv)G"
[ -f "$BF16" ] || {
  say "②' merged-flat → bf16 GGUF"
  ( cd "$LC" && "$PY" convert_hf_to_gguf.py "$ROOT/merged-flat" --outfile "$BF16" --outtype bf16 ) 2>&1 | tail -3
}
ls -l "$BF16"

say "③' quantize IQ2_S + ssm_alpha/ssm_beta=q8_0  (avail $(dfv)G)"
"$LC/build/bin/llama-quantize" --imatrix "$ROOT/imatrix.dat" \
  --tensor-type ssm_alpha=q8_0 --tensor-type ssm_beta=q8_0 \
  "$BF16" "$IQ2S" IQ2_S 16 2>&1 | tail -6
ls -l "$IQ2S"

say "④' 删 bf16"
rm -f "$BF16"
say "free $(dfv)G"

say "⑤' GGUF → .ninfer（recipe qwen3_8_27b_gguf）"
( cd "$CONV" && "$PY" -m tools.convert \
    --model "$ROOT/merged-cfg/Qwen3.8-27B-kittyrev" \
    --recipe qwen3_8_27b_gguf \
    --source "gguf=$IQ2S" \
    --components text \
    --name qwen3.8-27b-kittyrev-iq2s \
    --out "$OUT" ) 2>&1 | tail -10

ls -lh "$OUT"
say "⑥ inspect"
( cd "$CONV" && "$PY" -m tools.artifact.inspect "$OUT" --json ) > /root/iq2s_inspect.json
"$PY" - <<'PYEOF'
import json
d=json.load(open('/root/iq2s_inspect.json'))
print('objects',d.get('objects'),'tensors',d.get('tensors'),'file_bytes',d.get('file_bytes'))
print('formats',json.dumps(d.get('formats'),ensure_ascii=False))
print('layouts',json.dumps(d.get('layouts'),ensure_ascii=False))
PYEOF
say "DONE"
