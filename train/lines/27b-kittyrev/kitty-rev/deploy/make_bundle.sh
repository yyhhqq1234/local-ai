#!/usr/bin/env bash
# make_bundle.sh —— 打包"要上传到云卡"的全部内容（不含权重，基座到云端现拉）
# 用法：bash make_bundle.sh            # 产出 deploy/kitty-rev-bundle-<date>.tar.gz
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)          # .../train/lines/27b-kittyrev/kitty-rev/deploy
KR=$(cd "$HERE/.." && pwd)                   # .../train/lines/27b-kittyrev/kitty-rev
TRAIN=$(cd "$KR/.." && pwd)                  # .../train
STAMP=$(date +%Y%m%d-%H%M)
OUT=${OUT:-$HERE/kitty-rev-bundle-$STAMP.tar.gz}
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/kitty-rev/data" "$STAGE/scripts" "$STAGE/ninfer-master" "$STAGE/cloud"

echo "[1/5] kitty-rev：脚本 / 验收 / 契约"
cp -r "$KR/scripts" "$KR/eval" "$KR/contracts" "$STAGE/kitty-rev/"
for f in README.md RUNBOOK.md REASONING-DATA.md docs-12gb-feasibility.md; do
  [ -f "$KR/$f" ] && cp "$KR/$f" "$STAGE/kitty-rev/"
done

echo "[2/5] 数据（large / large-mix / reasoning）"
cp -r "$KR/data/large" "$STAGE/kitty-rev/data/"
cp -r "$KR/data/large-mix" "$STAGE/kitty-rev/data/"
[ -d "$KR/data/reasoning" ] && cp -r "$KR/data/reasoning" "$STAGE/kitty-rev/data/"

echo "[3/5] 训练侧脚本"
cp "$TRAIN/scripts/merge.py" "$TRAIN/scripts/fetch_base.py" "$TRAIN/scripts/dl_base_curl.py" "$STAGE/scripts/"
[ -f "$TRAIN/scripts/verify_base.py" ] && cp "$TRAIN/scripts/verify_base.py" "$STAGE/scripts/" || true

echo "[4/5] converter 源码（排除 venv / cache）"
( cd "$TRAIN/tools/ninfer-master" && \
  tar -cf - --exclude='.venv-convert' --exclude='__pycache__' --exclude='.git' \
             --exclude='.agent-tmp' --exclude='out' . ) | tar -xf - -C "$STAGE/ninfer-master"

echo "[5/5] 云端脚本（setup / run_all / README）"
cp "$HERE/cloud/"*.sh "$HERE/cloud/"*.md "$STAGE/cloud/"

tar -czf "$OUT" -C "$STAGE" .
echo "bundle: $OUT"
du -h "$OUT" | awk '{print "size: "$1}'
echo "entries: $(tar -tzf "$OUT" | wc -l)"
