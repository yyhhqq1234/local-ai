#!/usr/bin/env bash
# Batch B: __pycache__ dirs -> _trash/20261022-1311/pycache (skip tracked-pyc dirs)
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
DST=$ROOT/_trash/20261022-1311/pycache
mkdir -p "$DST" || exit 1
cd "$ROOT" || exit 1
SKIP="train/lines/27b-kittyrev/kitty-rev/deploy/cloud/__pycache__ train/lines/27b-kittyrev/kitty-rev/eval/__pycache__ train/lines/27b-kittyrev/kitty-rev/scripts/__pycache__"
before=$(du -sk . 2>/dev/null | awk '{print $1}')
n=0; moved=0
find . -path ./.git -prune -o -path ./_trash -prune -o -type d -name __pycache__ -print 2>/dev/null | sed 's|^\./||' | sort > _work/disk-janitor/pyc.list
total=$(wc -l < _work/disk-janitor/pyc.list)
echo "found=$total"
while IFS= read -r p; do
  n=$((n+1))
  skip=0
  for s in $SKIP; do [ "$p" = "$s" ] && skip=1; done
  if [ $skip -eq 1 ]; then echo "SKIP(tracked pyc): $p"; continue; fi
  [ -d "$p" ] || { echo "MISS: $p"; continue; }
  name=$(echo "$p" | sed 's|/__pycache__$||; s|/|__|g')
  mv -- "$p" "$DST/${name}__pycache__" || { echo "FAIL: $p"; continue; }
  moved=$((moved+1))
  if [ $((n % 500)) -eq 0 ]; then echo "CHK n=$n moved=$moved trash=$(ls -A "$DST" | wc -l)"; fi
done < _work/disk-janitor/pyc.list
after=$(du -sk . 2>/dev/null | awk '{print $1}')
echo "AFTER ws_kb=$after freed_kb=$((before-after)) moved=$moved trash_dirs=$(ls -A "$DST" | wc -l)"
