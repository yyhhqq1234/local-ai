#!/usr/bin/env bash
# run_iq2s_path.sh —— 把 16 G 的 .ninfer 换成 <10 G（IQ2_S 直通）
#
# 原理：新版 ninfer-all-master 的 recipe `qwen3_8_27b_gguf`（gguf_blocks.py:555）
#       逐 tensor 按 GGUF block type 原样搬进 .ninfer v3（method=import_encoded，不重量化）
#       → IQ2_S payload 8.8 G → .ninfer ≈ 9.4 G
#
# 前置：云端已有 merged/Qwen3.8-27B-kittyrev（51 G）+ imatrix.dat
# 用法：bash run_iq2s_path.sh check | build | all
set -eu

ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
PY=${PY:-/root/miniconda3/bin/python}
MERGED=$ROOT/merged/Qwen3.8-27B-kittyrev
CFGDIR=$ROOT/merged-cfg/Qwen3.8-27B-kittyrev
GGUF=$ROOT/gguf
IMAT=$ROOT/imatrix.dat
CONV=$ROOT/ninfer-all-master
BF16=$GGUF/qwen38_kittyrev_bf16.gguf
IQ2S=$GGUF/qwen38_kittyrev_iq2s.gguf
OUT=$ROOT/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer
LCPP=${LCPP:-/tmp/lc}

dfv() { df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9'; }
say() { echo "[$(date +%H:%M:%S)] $*"; }
need_g() {
  local need=$1 why=$2 avail; avail=$(dfv)
  say "need  ${need}G  avail ${avail}G  ($why)"
  [ "$avail" -ge "$need" ] || { echo "[FATAL] 磁盘不足: 需要 ${need}G 可用 ${avail}G — $why"; exit 1; }
}

prepare_cfg() {
  say "① 造纯文本 config 目录（recipe 只需 config + tokenizer，不收权重）"
  mkdir -p "$CFGDIR"
  "$PY" - "$MERGED" "$CFGDIR" <<'PYEOF'
import json, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
cfg = json.load(open(os.path.join(src, "config.json")))
tc = cfg.get("text_config") or {}
for k in ("vision_config", "image_token_id", "video_token_id", "vision_start_token_id",
          "vision_end_token_id", "language_model_only", "text_config"):
    cfg.pop(k, None)
for k, v in tc.items():
    if k in ("architectures", "model_type"):
        continue
    cfg.setdefault(k, v)
cfg["architectures"] = ["Qwen3_5ForCausalLM"]
cfg["model_type"] = "qwen3_5_text"
json.dump(cfg, open(os.path.join(dst, "config.json"), "w"), ensure_ascii=False, indent=2)
n = 0
for name in os.listdir(src):
    if name.endswith((".jinja", ".json")) and name != "config.json" and "safetensors" not in name:
        shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
        n += 1
print(f"[cfg] architectures={cfg['architectures']} model_type={cfg['model_type']} "
      f"hidden={cfg.get('hidden_size')} layers={cfg.get('num_hidden_layers')} files={n}")
PYEOF
}

ensure_lcpp() {
  if [ -x "$LCPP/build/bin/llama-quantize" ] && [ -f "$LCPP/convert_hf_to_gguf.py" ]; then
    say "llama.cpp 已就绪: $LCPP"; return
  fi
  say "llama.cpp 缺失 → 克隆 + 编译（gh-proxy.com，~10 min）"
  rm -rf "$LCPP"
  timeout 300 git clone --depth 1 https://gh-proxy.com/https://github.com/ggml-org/llama.cpp.git "$LCPP" 2>&1 | tail -2
  cmake -B "$LCPP/build" "$LCPP" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF >/dev/null
  cmake --build "$LCPP/build" -j16 --target llama-quantize 2>&1 | tail -3
  [ -x "$LCPP/build/bin/llama-quantize" ] || { echo "[FATAL] llama-quantize 编译失败"; exit 1; }
}

step_bf16() {
  need_g 56 "bf16 GGUF 54G"
  say "② merged → bf16 GGUF（约 4 min）"
  mkdir -p "$GGUF"
  ( cd "$LCPP" && "$PY" convert_hf_to_gguf.py "$MERGED" --outfile "$BF16" --outtype bf16 ) 2>&1 | tail -5
  ls -l "$BF16"
}

step_quant() {
  [ -f "$IMAT" ] || { echo "[FATAL] 缺 imatrix: $IMAT（IQ2_S 强制要求）"; exit 1; }
  need_g 12 "IQ2_S 输出 10G"
  say "③ bf16 → IQ2_S（带 imatrix，约 22 min）"
  "$LCPP/build/bin/llama-quantize" --imatrix "$IMAT" "$BF16" "$IQ2S" IQ2_S 16 2>&1 | tail -6
  ls -l "$IQ2S"
  say "④ 删 bf16 回收 54G"
  rm -f "$BF16"
  local avail; avail=$(dfv); say "free=${avail}G"
}

step_ninfer() {
  [ -d "$CONV/tools/convert" ] || { echo "[FATAL] 缺新版转换器: $CONV（先上传 ninfer-all-master.tar.gz 并解包）"; exit 1; }
  need_g 12 "ninfer 输出 10G"
  say "⑤ GGUF → .ninfer（recipe qwen3_8_27b_gguf，字节直通，约 5-8 min）"
  ( cd "$CONV" && "$PY" -m tools.convert \
      --model "$CFGDIR" \
      --recipe qwen3_8_27b_gguf \
      --source "gguf=$IQ2S" \
      --components text \
      --name qwen3.8-27b-kittyrev-iq2s \
      --out "$OUT" ) 2>&1 | tail -12
  ls -l "$OUT"
  say "⑥ inspect 校验"
  ( cd "$CONV" && "$PY" -m tools.artifact.inspect "$OUT" --json ) \
    | "$PY" -c "import json,sys;d=json.load(sys.stdin);print('objects',d.get('objects'),'tensors',d.get('tensors'),'bytes',d.get('file_bytes'));print('formats',json.dumps(d.get('formats'),ensure_ascii=False))"
}

cmd=${1:-check}
case "$cmd" in
  check)
    say "=== 体检 ==="
    say "merged  $(du -sh "$MERGED" 2>/dev/null | cut -f1 || echo MISSING)"
    say "imatrix $([ -f "$IMAT" ] && ls -lh "$IMAT" | awk '{print $5}' || echo MISSING)"
    say "converter $([ -d "$CONV/tools/convert" ] && echo OK || echo MISSING)"
    say "llama.cpp $([ -x "$LCPP/build/bin/llama-quantize" ] && echo OK || echo MISSING)"
    say "disk $(dfv)G avail"
    say "已有的 .ninfer:"; ls -lh "$ROOT/ninfer/"*.ninfer 2>/dev/null | awk '{print "  ",$5,$9}'
    ;;
  build) ensure_lcpp ;;
  all)
    need_g 60 "起步：bf16 54G + 余量"
    prepare_cfg; ensure_lcpp; step_bf16; step_quant; step_ninfer
    say "全部完成"
    ;;
  *) echo "用法: $0 check|build|all"; exit 2 ;;
esac
