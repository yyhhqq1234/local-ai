#!/usr/bin/env bash
# pull12.sh —— 12 路并行拉取云端已切好的 12 片，合并 + 双侧 md5
set -uo pipefail
K=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev
OUT=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/local-pack/qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-iq2s-mtp.ninfer
TMP=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev/tmp/_p12
cd "$K" || exit 2
export MSYS2_ARG_CONV_EXCL='*'
export AUTODL_HOST=123.127.15.155
export PATH="/c/ProgramData/anaconda3:/c/ProgramData/anaconda3/Scripts:$PATH"
mkdir -p "$TMP"

echo "[1/4] 片清单 $(date '+%H:%M:%S')"
python deploy/remote.py --cmd 'ls -1 /root/autodl-tmp/sp/f4.part.* | sed "s#.*/##"' | tr -d '\r' | grep part > "$TMP/list.txt"
N=$(wc -l < "$TMP/list.txt"); echo "  片数=$N"

echo "[2/4] 12 路并行 $(date '+%H:%M:%S')"
cat "$TMP/list.txt" | xargs -P 12 -I{} bash -c '
  f="{}"; out="'"$TMP"'/$f"
  if [ -s "$out" ] && [ "$(stat -c%s "$out")" -ge 1000000 ]; then echo "skip $f"; exit 0; fi
  python deploy/remote.py --get "/root/autodl-tmp/sp/$f" "$out" >/dev/null 2>&1
  echo "$f $(stat -c%s "$out" 2>/dev/null || echo 0)"
'
echo "  完成 $(date '+%H:%M:%S')"

echo "[3/4] 合并 $(date '+%H:%M:%S')"
: > "$OUT"
for f in $(cat "$TMP/list.txt"); do cat "$TMP/$f" >> "$OUT"; done
ls -la "$OUT"

echo "[4/4] md5 $(date '+%H:%M:%S')"
LM=$(md5sum "$OUT" | cut -d' ' -f1)
RM=5268030f117d11b1902425654fb88d4e
echo "  local =$LM"; echo "  remote=$RM"
if [ "$LM" = "$RM" ]; then echo "[VERDICT] PASS"; rm -rf "$TMP"; else echo "[VERDICT] FAIL"; fi
