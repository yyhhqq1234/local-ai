#!/usr/bin/env bash
# Batch E (lead-approved): 5 ASK items -> _trash/20261022-1318/
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
T=$ROOT/_trash/20261022-1318
cd "$ROOT" || exit 1
mkdir -p "$T/local-pack" "$T/base" "$T/ninfer-27b-logs" "$T/ninfer-csunx"

move_one() {
  src=$1; dst=$2
  if [ ! -e "$src" ]; then echo "MISS $src"; return; fi
  kb=$(du -sk "$src" | awk '{print $1}')
  bytes=$(stat -c '%s' "$src" 2>/dev/null || echo "-")
  ls -ld "$src" | awk '{print "PRE:", $1, $5, $9}'
  mv -- "$src" "$dst"/ && echo "MOVED $src  kb=$kb bytes=$bytes  -> $dst" || echo "FAIL $src"
}

move_one train/lines/27b-kittyrev/local-pack/merged-layers      "$T/local-pack"
move_one train/lines/27b-kittyrev/local-pack/act-cache          "$T/local-pack"
move_one train/lines/27b-kittyrev/base/Qwen3.8-27B-layers       "$T/base"
move_one ninfer-27b-kv-stream-3arch-20261019/logs/alt-prefix33.bin             "$T/ninfer-27b-logs"
move_one ninfer-27b-kv-stream-3arch-20261019/logs/prefix-cache-12g-hybrid.bin  "$T/ninfer-27b-logs"
move_one ninfer-27b-kv-stream-3arch-20261019/logs/alt-prefix.bin               "$T/ninfer-27b-logs"
move_one ninfer-csunx/engine.zip             "$T/ninfer-csunx"

echo "--- trash tree:"
ls -A "$T"; echo
for d in "$T"/*; do echo "$(basename "$d"): $(ls -A "$d" | tr '\n' ' ')"; done
echo "--- source gone check:"
for p in train/lines/27b-kittyrev/local-pack/merged-layers train/lines/27b-kittyrev/local-pack/act-cache train/lines/27b-kittyrev/base/Qwen3.8-27B-layers ninfer-csunx/engine.zip; do
  [ -e "$p" ] && echo "STILL THERE: $p" || echo "GONE: $p"
done
for f in alt-prefix33.bin prefix-cache-12g-hybrid.bin alt-prefix.bin; do
  p="ninfer-27b-kv-stream-3arch-20261019/logs/$f"
  [ -e "$p" ] && echo "STILL THERE: $p" || echo "GONE: $p"
done
echo "--- local-pack now:"; ls -la train/lines/27b-kittyrev/local-pack | awk '{print $5, $9}'
