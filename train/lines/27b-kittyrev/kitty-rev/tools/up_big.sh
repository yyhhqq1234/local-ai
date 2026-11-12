#!/usr/bin/env bash
# up_big.sh —— 通用分块并行上传（每块校验 size，坏块只重传该块）
# 用法：bash up_big.sh <本地文件> <云端目标路径> [并发=8] [块大小MB=200]
set -uo pipefail
SRC=$1; DST=$2; P=${3:-8}; MB=${4:-200}
K=/d/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev
cd "$K" || exit 2
export MSYS2_ARG_CONV_EXCL='*'
export AUTODL_HOST=123.127.15.155
export PATH="/c/ProgramData/anaconda3:/c/ProgramData/anaconda3/Scripts:$PATH"

BASE=$(basename "$DST")
CDIR=$(dirname "$DST")
CH=$K/tmp/_up_$BASE
rm -rf "$CH"; mkdir -p "$CH"
echo "[1/4] 切块 ${MB}MB → $CH"
split -b ${MB}M -a 3 --numeric-suffixes=0 "$SRC" "$CH/c."
N=$(ls "$CH" | wc -l); echo "  块数=$N  总=$(stat -c%s "$SRC")"

echo "[2/4] 云端清位 + 逐块上传（并发 $P）"
python deploy/remote.py --cmd "mkdir -p '$CDIR' && rm -f '$CDIR/$BASE' '$CDIR/$BASE.chunk.'*" >/dev/null 2>&1
ls "$CH" | xargs -P "$P" -I{} bash -c '
  f="{}"; C="'"$CH"'"; D="'"$CDIR"'"; B="'"$BASE"'"
  sz=$(stat -c%s "$C/$f")
  for t in 1 2 3 4 5; do
    r=$(python deploy/remote.py --cmd "stat -c%s \"$D/$B.chunk.$f\" 2>/dev/null" 2>/dev/null | tr -d "\r" | tail -1)
    [ "$r" = "$sz" ] && exit 0
    python deploy/remote.py --put "$C/$f" "$D/$B.chunk.$f" >/dev/null 2>&1
  done
  echo "FAIL $f"
'

echo "[3/4] 云端拼接"
python deploy/remote.py --cmd "cd '$CDIR' && rm -f '$BASE' && for i in \$(ls '$BASE'.chunk.* | sort); do cat \$i >> '$BASE'; done; echo size=\$(stat -c%s '$BASE'); rm -f '$BASE'.chunk.*" 2>&1 | tail -2

echo "[4/4] 本地体积对照"
echo "  local=$(stat -c%s "$SRC")"
rm -rf "$CH"
