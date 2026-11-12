#!/usr/bin/env bash
# dl_oxcoder9b.sh — OxCoder-9B 基座 + metadata 并行分片下载（hf-mirror）
#
# 为什么是分片并行：hf-mirror 最终存储返回 Accept-Ranges: bytes（实测 206 通过），
# 单连接实测 18 MB/s，17.53 GiB 单线程约 17 分钟；分片可线性叠加到线路带宽上限。
#
# 用法:
#   bash train/lines/_shared/scripts/dl_oxcoder9b.sh            # 12 分片
#   N=16 bash train/lines/_shared/scripts/dl_oxcoder9b.sh       # 16 分片
#   bash train/lines/_shared/scripts/dl_oxcoder9b.sh --meta-only
#
# 特性: 可重入（已完整的分片跳过）· 失败自动重试 · 合并后 sha256 校验
set -uo pipefail

ROOT="D:/BaiduNetdiskDownload/Local-AI"
DEST="$ROOT/train/lines/9b-oxcoder/models/OxCoder-9B"
META="$ROOT/train/lines/9b-oxcoder/models/metadata-oxcoder9b"
BASE="https://hf-mirror.com/OrionLLM/OxCoder-9B/resolve/main"
FILE="model.safetensors"
SIZE=18819722360
SHA="d4fca6821fe35b46e684ab88217ec25cdbfcdf9fa208c01110be95a200fcc33b"
N="${N:-12}"

META_FILES="config.json generation_config.json tokenizer.json tokenizer_config.json processor_config.json preprocessor_config.json chat_template.jinja"

mkdir -p "$DEST" "$META"
PARTS="$DEST/.parts"
mkdir -p "$PARTS"

echo "=== metadata ($META) ==="
for f in $META_FILES; do
  out="$META/$f"
  if [ -s "$out" ] && [ "$(stat -c%s "$out" 2>/dev/null || echo 0)" -gt 20 ]; then
    echo "  skip  $f"
    continue
  fi
  curl -sL --retry 5 --retry-delay 2 --max-time 300 -o "$out" "$BASE/$f"
  sz=$(stat -c%s "$out" 2>/dev/null || echo 0)
  if [ "$sz" -lt 20 ]; then echo "  FAIL  $f ($sz B)"; else echo "  ok    $f ($sz B)"; fi
done

if [ "${1:-}" = "--meta-only" ]; then echo "[meta-only] 退出"; exit 0; fi

PER=$(( (SIZE + N - 1) / N ))
echo ""
echo "=== 权重分片: $N 段 × ~$(( PER / 1048576 )) MiB / 共 $(awk -v s=$SIZE 'BEGIN{printf "%.2f", s/1073741824}') GiB ==="

pids=()
for ((i=0; i<N; i++)); do
  start=$(( i * PER ))
  end=$(( (i + 1) * PER - 1 ))
  [ "$end" -ge "$SIZE" ] && end=$(( SIZE - 1 ))
  want=$(( end - start + 1 ))
  part="$PARTS/part.$(printf '%02d' $i)"
  have=$(stat -c%s "$part" 2>/dev/null || echo 0)
  if [ "$have" -eq "$want" ]; then
    echo "  skip  $(basename $part) ($(( want / 1048576 )) MiB)"
    continue
  fi
  (
    curl -sL --retry 8 --retry-delay 3 --retry-all-errors \
         -r "${start}-${end}" -o "$part" \
         "$BASE/$FILE" \
      && echo "  done  $(basename $part)" \
      || echo "  ERR   $(basename $part)"
  ) &
  pids+=($!)
done

echo "  ... 等待 ${#pids[@]} 个分片"
for p in "${pids[@]:-}"; do [ -n "${p:-}" ] && wait "$p"; done

# 校验分片完整性
bad=0
for ((i=0; i<N; i++)); do
  start=$(( i * PER )); end=$(( (i + 1) * PER - 1 ))
  [ "$end" -ge "$SIZE" ] && end=$(( SIZE - 1 ))
  want=$(( end - start + 1 ))
  part="$PARTS/part.$(printf '%02d' $i)"
  have=$(stat -c%s "$part" 2>/dev/null || echo 0)
  if [ "$have" -ne "$want" ]; then echo "  [BAD] $(basename $part) have=$have want=$want"; bad=1; fi
done
if [ "$bad" -ne 0 ]; then
  echo ""
  echo "[FAIL] 有分片不完整。重跑本脚本即可续传（已完整的段会跳过）。"
  exit 2
fi

echo ""
echo "=== 合并 ==="
cat "$PARTS"/part.* > "$DEST/$FILE"
got=$(stat -c%s "$DEST/$FILE" 2>/dev/null || echo 0)
echo "  size = $got (期望 $SIZE)"

if [ "$got" -ne "$SIZE" ]; then
  echo "[FAIL] 合并后大小不符"; exit 3
fi

echo "=== sha256 校验（约 1-2 分钟）==="
sum=$(sha256sum "$DEST/$FILE" | awk '{print $1}')
if [ "$sum" = "$SHA" ]; then
  echo "  OK  $sum"
  rm -rf "$PARTS"
  echo ""
  echo "[DONE] $DEST/$FILE"
  echo "       释放分片目录 $PARTS"
else
  echo "  MISMATCH"
  echo "    got  = $sum"
  echo "    want = $SHA"
  echo "  → 保留分片，重跑本脚本会重校验；仍失败则删 .parts 全量重下"
  exit 4
fi
