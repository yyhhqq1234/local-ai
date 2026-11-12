#!/usr/bin/env bash
# 只读：把 git status 条目按 4+1 组归类，统计文件数/字节
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
LIST=_work/disk-janitor/status.list
git status --porcelain -uall | sed 's/^...//' | sort > "$LIST"

declare -A CNT BYTES
declare -A FILES
order="A B C D E X"

classify() {
  p=$1
  case "$p" in
    *__pycache__*|*.pyc) echo X; return;;
    _work/disk-janitor/*) echo X; return;;
    train/lines/27b-kittyrev/local-pack/kittyrev-local-pack.tar) echo X; return;;
    train/lines/27b-kittyrev/kitty-rev/scripts/*) echo A; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/cloud/*) echo B; return;;
    train/lines/27b-kittyrev/kitty-rev/data/*|train/lines/27b-kittyrev/kitty-rev/docs-local-*.md|train/lines/27b-kittyrev/kitty-rev/logs/*.md|TASKPOINT.md) echo C; return;;
    train/lines/27b-kittyrev/kitty-rev/deploy/base-meta/*|train/lines/27b-kittyrev/kitty-rev/deploy/fix_pack.sh|train/lines/27b-kittyrev/kitty-rev/deploy/local_train.ps1) echo D; return;;
    *) echo E; return;;
  esac
}

while IFS= read -r p; do
  [ -z "$p" ] && continue
  g=$(classify "$p")
  sz=0
  [ -f "$p" ] && sz=$(stat -c %s "$p" 2>/dev/null || echo 0)
  CNT[$g]=$(( ${CNT[$g]:-0} + 1 ))
  BYTES[$g]=$(( ${BYTES[$g]:-0} + sz ))
  FILES[$g]="${FILES[$g]:-}${p}	${sz}
"
done < "$LIST"

for g in A B C D E X; do
  c=${CNT[$g]:-0}; b=${BYTES[$g]:-0}
  printf "== %s : %s 个条目, %s B (%.2f MB)\n" "$g" "$c" "$b" "$(echo "scale=2; $b/1048576" | bc)"
done

for g in A B C D E X; do
  echo "----- $g 明细"
  printf "%s" "${FILES[$g]:-}"
done > _work/disk-janitor/plan-detail.txt
echo "detail -> _work/disk-janitor/plan-detail.txt ($(wc -l < _work/disk-janitor/plan-detail.txt) 行)"
