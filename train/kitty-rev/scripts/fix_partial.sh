#!/usr/bin/env bash
# 显式 Range 续尾修复：不改动已有字节、不删除文件，只追加缺失的尾巴
set -u
BASE="https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main"
DIR="D:/BaiduNetdiskDownload/Local-AI/train/base/Qwen3.8-27B"
cd "$DIR" || exit 1

fix_one() {
  local name="$1" want="$2"
  local have partsz expect
  have=$(stat -c %s "$name" 2>/dev/null || echo 0)
  echo "[fix] $name have=$have want=$want"
  if [ "$have" -ge "$want" ]; then echo "[fix] $name already full"; return 0; fi
  expect=$((want - have))
  curl -L -sS --retry 3 --retry-delay 2 -r "${have}-" -o "${name}.part" "$BASE/$name"
  local rc=$?
  partsz=$(stat -c %s "${name}.part" 2>/dev/null || echo 0)
  echo "[fix] $name curl_rc=$rc part=$partsz expect=$expect"
  if [ "$partsz" -ne "$expect" ]; then echo "[fix] PART-MISMATCH $name (keep .part)"; return 1; fi
  cat "${name}.part" >> "$name" || return 1
  local new; new=$(stat -c %s "$name")
  echo "[fix] $name appended -> $new (want $want)"
  if [ "$new" -eq "$want" ]; then rm -f "${name}.part"; echo "[fix] OK $name"; return 0; else echo "[fix] SIZE-MISMATCH $name"; return 1; fi
}

fix_one model-00008-of-00018.safetensors 3979553696
fix_one model-00018-of-00018.safetensors 3392197344
echo "[fix] done"
