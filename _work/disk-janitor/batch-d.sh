#!/usr/bin/env bash
# Batch D: empty dirs -> _trash/20261022-1311/empty-dirs (deepest first)
set -u
ROOT=/d/BaiduNetdiskDownload/Local-AI
T=$ROOT/_trash/20261022-1311/empty-dirs
cd "$ROOT" || exit 1
mkdir -p "$T"
find . -path ./.git -prune -o -path ./_trash -prune -o -type d -empty -print 2>/dev/null | sed 's|^\./||' \
  | awk -F/ '{print NF"\t"$0}' | sort -rn | cut -f2- > _work/disk-janitor/empty.list
echo "candidates=$(wc -l < _work/disk-janitor/empty.list)"
n=0
while IFS= read -r d; do
  [ -z "$d" ] && continue
  [ -d "$d" ] || { continue; }
  name=$(echo "$d" | sed 's|/|__|g')
  mv -- "$d" "$T/$name" 2>/dev/null && n=$((n+1)) || echo "SKIP(parent moved or busy): $d"
done < _work/disk-janitor/empty.list
echo "moved_empty=$n  trash_entries=$(ls -A "$T" | wc -l)"
echo "--- remaining empty dirs:"; find . -path ./.git -prune -o -path ./_trash -prune -o -type d -empty -print 2>/dev/null | head -10
