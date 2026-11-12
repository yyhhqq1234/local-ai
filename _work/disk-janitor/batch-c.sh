#!/usr/bin/env bash
# Batch C: legacy archives + redundant bak -> _trash
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
T=$ROOT/_trash/20261022-1311
cd "$ROOT" || exit 1
mkdir -p "$T/archives" "$T/bak"

items=(
"train/lines/_shared/tools/ninfer-master.zip|archives"
"train/lines/27b-kittyrev/kitty-rev/deploy/ninfer-all-master.tar.gz|archives"
"train/lines/27b-kittyrev/kitty-rev/deploy/cloud/run_after_expand.sh.bak-imatrix|bak"
)
for it in "${items[@]}"; do
  p=${it%%|*}; sub=${it##*|}
  if [ -f "$p" ]; then
    ls -la "$p" | awk '{print "PRE:", $5, $9}'
    mv -- "$p" "$T/$sub/" && echo "MOVED $p -> $sub" || echo "FAIL $p"
  else
    echo "MISS $p"
  fi
done
echo "--- archives:"; ls -la "$T/archives" | tail -n +2
echo "--- bak:"; ls -la "$T/bak" | tail -n +2
