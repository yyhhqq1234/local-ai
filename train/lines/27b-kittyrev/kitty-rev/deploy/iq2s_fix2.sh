#!/usr/bin/env bash
# iq2s_fix2.sh —— bf16 已存在，只跑：量化(保 ssm_*=q8_0) → 删 bf16 → 直通 .ninfer → inspect
set -eu
ROOT=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
BF16=$ROOT/gguf/bf16.gguf
IQ2S=$ROOT/gguf/qwen38_kittyrev_iq2s_v2.gguf
CONV=$ROOT/ninfer-all-master
OUT=$ROOT/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer

say() { echo "[$(date +%H:%M:%S)] $*"; }
dfv() { df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9'; }

[ -f "$BF16" ] || { echo "[FATAL] 缺 $BF16"; exit 1; }
say "③'' quantize IQ2_S + ssm_alpha/beta=q8_0   avail=$(dfv)G"
/tmp/lc/build/bin/llama-quantize \
  --imatrix "$ROOT/imatrix.dat" \
  --tensor-type ssm_alpha.weight=q8_0 --tensor-type ssm_beta.weight=q8_0 \
  "$BF16" "$IQ2S" IQ2_S 16 2>&1 | tail -5
ls -l "$IQ2S"

say "④'' 删 bf16"; rm -f "$BF16"; say "free $(dfv)G"

say "⑤'' GGUF → .ninfer"
( cd "$CONV" && "$PY" -m tools.convert \
    --model "$ROOT/merged-cfg/Qwen3.8-27B-kittyrev" \
    --recipe qwen3_8_27b_gguf \
    --source "gguf=$IQ2S" \
    --components text \
    --name qwen3.8-27b-kittyrev-iq2s \
    --out "$OUT" ) 2>&1 | tail -8

ls -lh "$OUT"
( cd "$CONV" && "$PY" -m tools.artifact.inspect "$OUT" --json ) > /root/iq2s_inspect.json
"$PY" - <<'PYEOF'
import json
d=json.load(open('/root/iq2s_inspect.json'))
print('objects',d.get('objects'),'tensors',d.get('tensors'),'file_bytes',d.get('file_bytes'))
print('formats',json.dumps(d.get('formats'),ensure_ascii=False))
print('layouts',json.dumps(d.get('layouts'),ensure_ascii=False))
PYEOF
say "DONE"
