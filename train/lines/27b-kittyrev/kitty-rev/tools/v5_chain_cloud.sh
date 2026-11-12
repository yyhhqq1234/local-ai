#!/bin/bash
# v5_chain_cloud.sh —— V5 云端全链（B 路径：意愿层训练后的量化 + vision）
#
# 前提：merged-v5 已就绪（训练 + merge 在本脚本之前完成，或本脚本只负责 M1 之后）
# 本脚本负责：
#   T1  base 下载 + G1（若无 merged 才需要）
#   T2  merge（若 adapter 已换 v5）
#   T3b mmproj（vision q8_0）
#   T3  IQ2_S 量化链（复用 chain_repair.py M1→M6，已改成含 vision）
#
# 用法：
#   bash tools/v5_chain_cloud.sh                # 全跑（含下载/merge）
#   bash tools/v5_chain_cloud.sh --from M1      # 直接进量化链（merged-v5 已就绪）
#   bash tools/v5_chain_cloud.sh --from T3b     # 只补 mmproj + 量化
set -u
R=/root/autodl-tmp/kitty-rev
PY=/root/miniconda3/bin/python
AD=$R/out-v5/adapter
MK=$R/logs/v5/.markers
LOG=$R/logs/v5/CHAIN-V5.log
MERGED=$R/merged-v5
MMP=$R/gguf/v5-mmproj-q8.gguf
IMX=$R/imatrix-v4r.dat

mkdir -p "$MK" "$(dirname "$LOG")" "$R/gguf"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
ok(){ echo "$2" > "$MK/$1.ok"; log "[$1] PASS $2"; }
has(){ [ -f "$MK/$1.ok" ]; }
stop(){ log "[STOP] $*"; exit 1; }
free_g(){ df -BG --output=avail /root/autodl-tmp | tail -1 | tr -dc '0-9'; }

FROM="T0"
[ "${1:-}" = "--from" ] && FROM="${2:-T0}"
log "===== V5 chain start from=$FROM ====="
log "[disk] free=$(free_g)G"

# ---------- T1 下载 ----------
if [ "$FROM" = "T0" ] && ! has T1; then
  log "----- T1 下载 base -----"
  $PY -u "$R/tools/dl_base_fast.py" --out "$R/base/Huihui" --list "$R/tmp/_base/shards.txt" \
      --conc 16 --seg-mb 16 >> "$LOG" 2>&1 || stop "T1 下载失败"
  ok T1 "downloaded"
fi

if [ "$FROM" = "T0" ] && ! has G1; then
  log "----- G1 完整性 -----"
  $PY -u "$R/tools/g1_check.py" --base "$R/base/Huihui" --list "$R/tmp/_base/shards.txt" >> "$LOG" 2>&1 \
    || stop "G1 FAIL"
  ok G1 "18 shards verified"
fi

# ---------- T2 merge ----------
if { [ "$FROM" = "T0" ] || [ "$FROM" = "T2" ]; } && ! has T2; then
  log "----- T2 merge(v5 adapter) -----"
  [ -f "$AD/adapter_model.safetensors" ] || stop "缺 v5 adapter: $AD"
  $PY -u "$R/tools/tensor_merge.py" --base "$R/base/Huihui" --adapter "$AD" \
      --out "$MERGED" --stream >> "$LOG" 2>&1 || stop "T2 merge 失败"
  N=$(ls "$MERGED"/*.safetensors 2>/dev/null | wc -l)
  [ "$N" -eq 18 ] || stop "T2 输出片数 $N != 18"
  for f in model.safetensors.index.json vocab.json video_preprocessor_config.json added_tokens.json; do
    [ -f "$R/base/Huihui/$f" ] && [ ! -f "$MERGED/$f" ] && cp "$R/base/Huihui/$f" "$MERGED/" && log "补拷 $f"
  done
  [ -f "$MERGED/model.safetensors.index.json" ] || stop "T2 后缺 index.json"
  ok T2 "shards=$N merged"
fi

[ -d "$MERGED" ] || stop "缺 merged-v5（先跑 T2 或训练+merge）"

# ---------- T3b mmproj（vision q8_0，操作者选定 B 档） ----------
if ! has T3b; then
  log "----- T3b mmproj(vision, q8_0) -----"
  if [ -f "$MMP" ]; then
    log "mmproj 已存在，跳过合成"
  else
    CONV=""
    for c in "$R/ninfer-all-master/convert_hf_to_gguf.py" "$R/lc/convert_hf_to_gguf.py"; do
      [ -f "$c" ] && CONV="$c" && break
    done
    [ -n "$CONV" ] || stop "找不到 convert_hf_to_gguf.py"
    log "using $CONV"
    $PY "$CONV" "$MERGED" --mmproj --outtype q8_0 --outfile "$MMP" >> "$LOG" 2>&1 \
      || stop "T3b mmproj 导出失败"
  fi
  [ -f "$MMP" ] || stop "T3b 无产物"
  MSZ=$(stat -c%s "$MMP")
  [ "$MSZ" -gt 300000000 ] || stop "T3b mmproj 太小 $MSZ（可能没转到 vision）"
  [ "$MSZ" -lt 700000000 ] || stop "T3b mmproj 太大 $MSZ（可能没量化成 q8_0）"
  ok T3b "mmproj=$MSZ"
fi

# ---------- T3 IQ2_S 量化链（chain_repair M1→M6，已含 vision） ----------
if ! has T3; then
  log "----- T3 IQ2_S 链（M1→M6，含 vision）-----"
  [ -f "$MMP" ] || stop "缺 mmproj（T3b 未完成）"
  [ -f "$IMX" ] || stop "缺 imatrix: $IMX"
  cd "$R" || stop "进不去 $R"
  $PY -u "$R/tools/chain_repair.py" --from M1 >> "$LOG" 2>&1
  RC=$?
  [ "$RC" -eq 0 ] || stop "T3 chain_repair rc=$RC（看日志哪一门红）"
  ok T3 "chain done"
fi

log "===== V5 chain DONE ====="
OUT=$(grep -oE '/root/autodl-tmp/kitty-rev/ninfer-v5/[^ ]+\.ninfer' "$LOG" | tail -1)
log "[result] $OUT"
echo
echo "=== 产物 ==="
ls -l "$R"/ninfer-v5/*.ninfer "$R"/ninfer-v5/*.conversion.json 2>/dev/null
echo "=== 组件与体积 ==="
cd "$R/ninfer-all-master" && $PY -m tools.artifact.inspect "$OUT" 2>/dev/null | \
  grep -E '^(file_bytes|objects|tensors|components|formats):' | cut -c1-220 || true
