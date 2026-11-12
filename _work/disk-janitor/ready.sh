#!/usr/bin/env bash
# 只读：按 D/B/A/C/X 五类统计 COMMIT-READY 清单
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
L=_work/disk-janitor/status.1705
OUT=_work/disk-janitor/ready-detail.txt
: > "$OUT"

classify() {
  p=$1
  case "$p" in
    .gitignore) echo D; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/base-meta/*) echo D; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/fix_pack.sh|train/lines/27b-kittyrev/kitty-rev/deploy/local_train.ps1) echo D; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/remote.py|train/lines/27b-kittyrev/kitty-rev/deploy/verify_local_pack.py) echo D; return;;
    train/lines/27b-kittyrev/local-pack/adapter_config.json) echo D; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/cloud/*) echo B; return;;
    train/lines/27b-kittyrev/kitty-rev/scripts/__pycache__/*|train/lines/27b-kittyrev/kitty-rev/eval/__pycache__/*) echo X; return;;
    train/lines/27b-kittyrev/kitty-rev/scripts/*) echo A; return;;
    train/lines/27b-kittyrev/kitty-rev/eval/eval_kitty.py) echo A; return;;
    train/lines/27b-kittyrev/kitty-rev/data/*|train/lines/27b-kittyrev/kitty-rev/docs-local-*.md|TASKPOINT.md) echo C; return;;
    *) echo X; return;;
  esac
}

declare -A CNT BYTES
while IFS= read -r p; do
  [ -z "$p" ] && continue
  g=$(classify "$p"); sz=0
  [ -f "$p" ] && sz=$(stat -c %s "$p" 2>/dev/null || echo 0)
  CNT[$g]=$(( ${CNT[$g]:-0} + 1 )); BYTES[$g]=$(( ${BYTES[$g]:-0} + sz ))
  echo "${g}|${sz}|${p}" >> "$OUT"
done < "$L"

for g in D B A C X; do
  c=${CNT[$g]:-0}; b=${BYTES[$g]:-0}
  awk -v g="$g" -v c="$c" -v b="$b" 'BEGIN{printf "%s: %d 个 / %d B (%.2f MiB)\n", g, c, b, b/1048576}'
done

echo "--- D 明细"; grep '^D|' "$OUT" | awk -F'|' '{printf "%9d  %s\n",$2,$3}'
echo "--- B 明细"; grep '^B|' "$OUT" | awk -F'|' '{printf "%9d  %s\n",$2,$3}'
echo "--- C 明细(按大小)"; grep '^C|' "$OUT" | sort -t'|' -k2 -rn | awk -F'|' '{printf "%9d  %s\n",$2,$3}' | head -25
echo "--- X 明细"; grep '^X|' "$OUT" | awk -F'|' '{printf "%9d  %s\n",$2,$3}'
