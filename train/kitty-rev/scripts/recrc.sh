#!/usr/bin/env bash
# 复核 3 个 CRC 不符的小文件：与镜像重新取一份对比 sha256（不覆盖原文件）
set -u
BASE="https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main"
DIR="D:/BaiduNetdiskDownload/Local-AI/train/base/Qwen3.8-27B"
TMP="D:/BaiduNetdiskDownload/Local-AI/train/kitty-rev/tmp"
mkdir -p "$TMP"
cd "$DIR" || exit 1
for n in chat_template.jinja generation_config.json tokenizer_config.json; do
  curl -L -sS --retry 2 -o "$TMP/$n" "$BASE/$n" || { echo "[net-fail] $n"; continue; }
  a=$(sha256sum "$n" | cut -d' ' -f1)
  b=$(sha256sum "$TMP/$n" | cut -d' ' -f1)
  sa=$(stat -c %s "$n"); sb=$(stat -c %s "$TMP/$n")
  if [ "$a" = "$b" ]; then
    echo "[MATCH] $n  local=$a size=$sa  (镜像同字节 → crc32.txt 上游过期)"
  else
    echo "[DIFF ] $n  local=$a($sa)  fresh=$b($sb)"
  fi
done
rm -rf "$TMP"
