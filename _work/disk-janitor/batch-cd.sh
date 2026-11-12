#!/usr/bin/env bash
# Batch C: legacy archives + redundant bak -> _trash ; Batch D: empty dirs
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
T=$ROOT/_trash/20261022-1311
cd "$ROOT" || exit 1
mkdir -p "$T/archives" "$T/bak" "$T/empty-dirs"

items=(
"train/lines/_shared/tools/ninfer-master.zip|archives"
"train/lines/27b-kittyrev/kitty-rev/deploy/ninfer-all-master.tar.gz|archives"
"train/lines/27b-kittyrev/kitty-rev/deploy/cloud/run_after_expand.sh.bak-imatrix|bak"
)
for it in "${items[@]}"; do
  p=${it%%|*}; sub=${it##*|}
  if [ -f "$p" ]; then
    sz=$(du -k "$p" | awk '{print $1}')
    ls -la "$p" | awk '{print "PRE:", $5, $9}'
    mv -- "$p" "$T/$sub/" && echo "MOVED $p (${sz}KB) -> $sub" || echo "FAIL $p"
  else
    echo "MISS $p"
  fi
done

echo "--- archives:"; ls -A "$T/archives"
echo "--- bak:"; ls -A "$T/bak"

# empty dirs (skip _trash and .git)
n=0
find . -path ./.git -prune -o -path ./_trash -prune -o -type d -empty -print 2>/dev/null | sed 's|^\./||' > _work/disk-janitor/empty.list
while IFS= read -r d; do
  [ -z "$d" ] && continue
  [ -d "$d" ] || continue
  name=$(echo "$d" | sed 's|/|__|g')
  mkdir -p "$T/empty-dirs/${name}"
  n=$((n+1))
done < _work/disk-janitor/empty.list
echo "EMPTY_DIRS recorded=$n (kept as mkdir stubs, originals left in place)"
cat _work/disk-janitor/empty.list
