#!/bin/bash
# finalize_gen2_iq2s.sh —— GSQ-RCO IQ2_S gguf → NInfer v3 .ninfer（gen2，纯文本，<10GB）
#
# 与 v6 的差异（v6 provenance 对照）：
#   v6: --model cfg-vision --source gguf=v6-mtp-spliced.gguf --components text,mtp
#   gen2: 无 MTP/vision 张量 → --components text；tokenizer 用 cfg-vision 那份
#         （merged-gen2 的 tokenizer_config.json 缺 added_tokens_decoder，引擎/转换都会 FATAL）
set -u
R=/root/autodl-tmp/kitty-rev
GGUF=$R/gguf/gen2-iq2s.gguf
CFG=$R/cfg-gen2
OUTDIR=$R/ninfer-gen2
OUT=$OUTDIR/qwen3.8-27b-kittyrev-gen2-gsqrco-iq2s.ninfer
PY=/root/miniconda3/bin/python

echo "===== 1) 体检 gguf ====="
$PY - "$GGUF" <<'EOF'
import sys, os, gguf
from collections import Counter
p=sys.argv[1]; sz=os.path.getsize(p)
r=gguf.GGUFReader(p)
c=Counter(gguf.GGMLQuantizationType(int(t.tensor_type)).name for t in r.tensors)
print("BYTES   =", sz, " (%.2f GiB)" % (sz/2**30))
print("IN_RANGE 9.0e9~10.737e9 =", 9.0e9 <= sz < 10.737e9)
print("N_TENS  =", len(r.tensors), "(gen2 无 MTP，期望 836；v6 含 blk.64 才是 851)")
print("TYPE_DIST =", dict(c))
ssm=[t for t in r.tensors if "ssm_alpha" in t.name or "ssm_beta" in t.name]
print("SSM_CNT =", len(ssm), "ALL_Q8_0 =", all(int(t.tensor_type)==8 for t in ssm) if ssm else "n/a")
bad = not (9.0e9 <= sz < 10.737e9) or (ssm and not all(int(t.tensor_type)==8 for t in ssm))
print("VERDICT =", "FAIL" if bad else "PASS")
EOF
rc=$?
[ $rc -ne 0 ] && { echo "[FATAL] gguf 体检失败"; exit 1; }

echo "===== 2) 备 cfg-gen2（补 added_tokens_decoder） ====="
mkdir -p "$CFG"
cp -f $R/merged-gen2/config.json $R/merged-gen2/generation_config.json "$CFG"/ 2>/dev/null
cp -f $R/cfg-vision/tokenizer.json $R/cfg-vision/tokenizer_config.json "$CFG"/ 2>/dev/null
cp -f $R/cfg-vision/chat_template.jinja "$CFG"/ 2>/dev/null
# 架构字段以 merged-gen2 为准（cfg-vision 是 VL 包装，arch 可能不同）
$PY - "$CFG" <<'EOF'
import json, sys, os
d=sys.argv[1]
cfg=json.load(open(os.path.join(d,'config.json')))
cfg.pop('vision_config', None)
json.dump(cfg, open(os.path.join(d,'config.json'),'w'), indent=1, ensure_ascii=False)
tk=json.load(open(os.path.join(d,'tokenizer_config.json')))
print("tokenizer added_tokens_decoder =", len(tk.get('added_tokens_decoder',{})))
print("arch =", cfg.get('architectures'), cfg.get('model_type'))
EOF

echo "===== 3) convert → .ninfer ====="
mkdir -p "$OUTDIR"
cd $R/ninfer-all-master
$PY -m tools.convert --model "$CFG" --recipe qwen3_8_27b_gguf \
  --source gguf="$GGUF" --components text \
  --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
  --name qwen3.8-27b-kittyrev-gen2-gsqrco --device cpu --out "$OUT" 2>&1 | tail -25

echo "===== 4) 结构自检 ====="
$PY -m tools.artifact.inspect "$OUT" 2>&1 | head -14
ls -l "$OUT"
$PY - "$OUT" <<'EOF'
import os,sys
sz=os.path.getsize(sys.argv[1])
print("NINFER BYTES =", sz, "(%.2f GiB)" % (sz/2**30), " <10GB =", sz < 10_000_000_000)
print("MAGIC =", open(sys.argv[1],'rb').read(4))
EOF
