#!/usr/bin/env bash
# Batch A: train/lines/27b-kittyrev/kitty-rev/tmp sandbox -> _trash (keep mix/ v41/ plan-opt/)
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
TMP=$ROOT/train/lines/27b-kittyrev/kitty-rev/tmp
DST=$ROOT/_trash/20261022-1311/train-kitty-rev-tmp
mkdir -p "$DST" || exit 1
cd "$TMP" || exit 1

before=$(du -sk "$TMP" | awk '{print $1}')
echo "BEFORE tmp_kb=$before"
echo "--- entries to move (ls preview) ---"
ls -A | grep -vE '^(mix|v41|plan-opt|__pycache__)$' | head -5
echo "..."
n=0
moved=0
for e in $(ls -A | grep -vE '^(mix|v41|plan-opt|__pycache__)$'); do
  n=$((n+1))
  if [ ! -e "$e" ]; then echo "MISS: $e"; continue; fi
  mv -- "$e" "$DST"/ || { echo "FAIL: $e"; continue; }
  moved=$((moved+1))
  if [ $((n % 10)) -eq 0 ]; then
    echo "CHK n=$n moved=$moved trash_entries=$(ls -A "$DST" | wc -l) src_dup=$(ls -A "$TMP" | wc -l)"
  fi
done
after=$(du -sk "$TMP" | awk '{print $1}')
echo "AFTER tmp_kb=$after  moved=$moved  freed_kb=$((before-after))"
echo "--- trash count: $(ls -A "$DST" | wc -l)"
echo "--- remaining in tmp:"; ls -A "$TMP"
