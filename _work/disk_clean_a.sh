#!/usr/bin/env bash
# A 批磁盘清理（低风险：可重建 / 无保留价值）
# 纪律：禁删清单（models/ 基座、.venv、ninfer-*、plugins、27b base、gen7 最终 ninfer）一律不碰
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1

BEFORE=$(df -m /d | awk 'NR==2{print $4}')
echo "=================================================================="
echo "A 批清理开始  D: 可用 ${BEFORE} MiB"
echo "=================================================================="

before_total=0

# del_dir <路径> <说明>
del_dir() {
  local p="$1" note="$2"
  if [ ! -e "$p" ]; then
    printf "  [skip] %-58s 不存在\n" "$p"
    return
  fi
  local sz
  sz=$(du -sm "$p" 2>/dev/null | awk '{print $1}')
  [ -z "$sz" ] && sz=0
  rm -rf "$p"
  if [ -e "$p" ]; then
    printf "  [FAIL] %-58s 删不掉（句柄占用？）\n" "$p"
  else
    printf "  [ok]   %-58s -%s MiB  (%s)\n" "$p" "$sz" "$note"
    before_total=$((before_total + sz))
  fi
}

echo "[1] 9B SRA 两档的中间 checkpoint（final 保留）"
for ck in train/lines/9b-oxcoder/out/z-re-sra-v1/checkpoint-*; do
  del_dir "$ck" "失败品中间件"
done
for ck in train/lines/9b-oxcoder/out/z-re-sra-r3-v1/checkpoint-*; do
  del_dir "$ck" "否证样本中间件"
done

echo "[2] HF datasets arrow 缓存（源 jsonl 在 data/，用时自动重建）"
del_dir "train/lines/_shared/hf/datasets" "arrow 缓存可重建"

echo "[3] 陈旧 fetch 中间件"
del_dir "train/lines/9b-oxcoder/out/gen3-fetch" "2026-10-30 中间件"

echo "[4] 27B gen7 的 adapter 中间件（最终 .ninfer 已出）"
for ck in train/lines/27b-kittyrev/local-pack/gen7/checkpoint-*; do
  del_dir "$ck" "adapter 中间件"
done
del_dir "train/lines/27b-kittyrev/local-pack/gen3_1p/adapter-600" "旧档 adapter"

echo "[5] 空壳目录"
del_dir "train/lines/9b-oxcoder/models/OxCoder-9B-sra-dryrun" "dry-run 空壳"
del_dir "train/lines/9b-oxcoder/models/merged-zre-v4" "空壳"

AFTER=$(df -m /d | awk 'NR==2{print $4}')
echo "=================================================================="
echo "脚本累计释放 ${before_total} MiB"
echo "D: 可用 ${BEFORE} -> ${AFTER} MiB  （净增 $((AFTER - BEFORE)) MiB）"
echo "=================================================================="

echo
echo "===== 复核：禁删项仍在 ====="
for keep in \
  train/lines/9b-oxcoder/models/OxCoder-9B \
  train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0 \
  train/lines/9b-oxcoder/out/z-re-v4/final \
  train/lines/9b-oxcoder/out/re-stage1-r3/final \
  train/lines/9b-oxcoder/out/z-2a-v7/final \
  train/lines/9b-oxcoder/out/2b-nsfw-v2/final \
  train/lines/9b-oxcoder/out/z-re-sra-r3-v1/final \
  train/lines/27b-kittyrev/base/Qwen3.8-27B \
  train/lines/27b-kittyrev/local-pack/gen7 \
  train/.venv \
  ninfer-csunx \
  ninfer-27b-kv-stream-3arch-20261019 \
  plugins ; do
  if [ -e "$keep" ]; then
    printf "  OK   %-64s %s\n" "$keep" "$(du -sh "$keep" 2>/dev/null | awk '{print $1}')"
  else
    printf "  MISS %-64s ★异常\n" "$keep"
  fi
done
