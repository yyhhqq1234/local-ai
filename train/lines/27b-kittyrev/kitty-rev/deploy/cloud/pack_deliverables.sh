#!/usr/bin/env bash
# pack_deliverables.sh —— 把两个交付物打成「可分批、可校验、可分通道传输」的包
#
# 产出的两个包走不同通道：
#   deliver1-ninfer.tar   10 GiB  → SSH 32 流（约 10-17 min）
#   deliver2-trainpack.tar 21 GiB → 网盘上传（有会员时 18-27 min）
#
# 用法：
#   bash cloud/pack_deliverables.sh check    # 只列清单不打包
#   bash cloud/pack_deliverables.sh pack     # 打包
set -euo pipefail

ROOT=${ROOT:-/root/autodl-tmp/kitty-rev}
OUT=${OUT:-$ROOT/deliver}
PY=${PY:-/root/miniconda3/bin/python}
NINFER=$ROOT/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer
LAYERS=$ROOT/merged-layers
ACT=$ROOT/act-cache
# ★ 单一约定：tar 里的 act-cache 目录**永远**叫 act-cache。
#   理由：本机 local_train.ps1 与 verify_local_pack.py 都按 act-cache/ 硬编码查
#   （v4 云端产出的目录叫 act-cache-v4，若原样进包，本地一键训练会死在"缺 act-cache"）。
#   所以在这里用 --transform 改名，而不是去改本机脚本 —— 约定只有一处，改一处就够。
ACT_SRC=${ACT_SRC:-$ACT}          # 源目录（v4 传 ACT_SRC=$ROOT/kitty-rev/act-cache-v4）
ACT_NAME=${ACT_NAME:-act-cache}   # 包内名字（不要改）
ACT_SRC_BASE=$(basename "$ACT_SRC")
ADAPTER=$ROOT/out/adapter-full3ep

say() { echo; echo "===== $* ====="; }
dfv() { df -h "$ROOT" | tail -1 | awk '{print $4}'; }

case "${1:-check}" in

check)
  say "交付物清单"
  printf "%-52s %10s\n" "文件" "大小"
  for f in "$NINFER" "$LAYERS/layer_48.safetensors" "$LAYERS/head.safetensors" "$ADAPTER/adapter_model.safetensors"; do
    if [ -f "$f" ]; then printf "%-52s %10s\n" "$(basename "$f")" "$(du -h "$f" | cut -f1)";
    else printf "%-52s %10s\n" "$(basename "$f")" "MISSING"; fi
  done
  echo
  echo "层文件数        : $(ls "$LAYERS"/layer_*.safetensors 2>/dev/null | wc -l)（应为 16，layer_48..63）"
  echo "act 源目录      : $ACT_SRC（包内将改名为 ${ACT_NAME}/）"
  echo "act-cache 子目录: $(ls -d "$ACT_SRC"/*/ 2>/dev/null | wc -l)（v4 期望 11：10 子集 + rest）"
  for d in "$ACT_SRC"/*/; do
    [ -d "$d" ] && echo "  $(basename "$d"): $(ls "$d"/*.pt 2>/dev/null | wc -l) 个 .pt"
  done
  echo
  echo "磁盘可用: $(dfv)"
  ;;

pack)
  say "① 交付物1：.ninfer（SSH 32 流）"
  [ -f "$NINFER" ] || { echo "[FATAL] 缺 $NINFER"; exit 1; }
  mkdir -p "$OUT"
  ( cd "$(dirname "$NINFER")" && tar -cf "$OUT/deliver1-ninfer.tar" "$(basename "$NINFER")" )
  ls -lh "$OUT/deliver1-ninfer.tar"

  say "② 交付物2：训练包（网盘）"
  [ -d "$LAYERS" ] || { echo "[FATAL] 缺 $LAYERS"; exit 1; }
  [ -d "$ACT_SRC" ] || { echo "[FATAL] 缺 $ACT_SRC（用 ACT_SRC=… 指定，v4 一般是 \$ROOT/kitty-rev/act-cache-v4）"; exit 1; }
  # --transform：把源目录名统一改写成 act-cache（见文件头 ACT_NAME 的理由）。
  # 正则**不带**结尾斜杠：带斜杠时 GNU tar 会把顶层目录条目 `act-cache-v4/` 原样留下，
  # 解包后多一个空目录（实测），不带斜杠则目录条目与子路径一起改名。
  ( cd "$ROOT" && tar -cf "$OUT/deliver2-trainpack.tar" \
      --transform "s,^${ACT_SRC_BASE},${ACT_NAME}," \
      merged-layers/layer_4[89].safetensors merged-layers/layer_5*.safetensors \
      merged-layers/layer_6*.safetensors merged-layers/head.safetensors \
      merged-layers/layers_index.json "$ACT_SRC" )
  ls -lh "$OUT/deliver2-trainpack.tar"
  echo "tar 内 act 目录名：$(tar -tf "$OUT/deliver2-trainpack.tar" | awk -F/ 'NR==1||/^act/{print $1}' | sort -u | tr '\n' ' ')"
  echo "（必须是 ${ACT_NAME}/；若是 ${ACT_SRC_BASE}/ 说明 --transform 没生效）"

  say "③ adapter（160 MB，单独传，叠加用）"
  if [ -d "$ADAPTER" ]; then
    ( cd "$(dirname "$ADAPTER")" && tar -cf "$OUT/deliver3-adapter.tar" "$(basename "$ADAPTER")" )
    ls -lh "$OUT/deliver3-adapter.tar"
  else
    echo "[warn] 无 $ADAPTER"
  fi

  say "④ 生成校验清单"
  ( cd "$OUT" && for f in *.tar; do
      echo "$(md5sum "$f" | cut -d' ' -f1)  $(stat -c%s "$f")  $f"
    done | tee MANIFEST.txt )
  echo
  echo "磁盘可用: $(dfv)"
  echo "OUT=$OUT"
  ;;

*) echo "用法: bash cloud/pack_deliverables.sh check|pack"; exit 1 ;;
esac
