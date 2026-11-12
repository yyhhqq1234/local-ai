#!/usr/bin/env bash
# 双线真实分家：把 train/{models,out,data,base,local-pack,kitty-rev,scripts,logs,...}
# 物理移动到 train/lines/<line>/ 下（不用 junction），并改写脚本/文档里的路径引用。
# 前置：训练必须已停（Windows 无法重命名有打开句柄的目录）
set -eu
cd "$(dirname "$0")/../.." || exit 1
echo "== 0) 前置检查 =="
if ps -ef | grep -q "[t]rain_qlora9b"; then echo "[FATAL] 训练仍在跑，先停"; exit 1; fi
echo "训练已停 · 磁盘:"; df -h /d | tail -1

echo "== 1) 清理旧 junction =="
for p in train/lines/9b-oxcoder/models train/lines/9b-oxcoder/out \
         train/lines/9b-oxcoder/data-kitty-reverse train/lines/9b-oxcoder/data-agent-traj \
         train/lines/9b-oxcoder/data-nsfw-gated train/lines/9b-oxcoder/data-eval \
         train/lines/27b-kittyrev/base train/lines/27b-kittyrev/local-pack \
         train/lines/27b-kittyrev/data-versions train/lines/27b-kittyrev/kitty-rev \
         train/lines/_shared/data-nsfw train/lines/_shared/data-raw train/lines/_shared/scripts; do
  [ -e "$p" ] && { cmd //c "rmdir $(echo "$p" | tr '/' '\\')" 2>/dev/null || rm -rf "$p"; echo "rm link $p"; }
done

echo "== 2) 建目标目录 =="
mkdir -p train/lines/9b-oxcoder/{models,out,data,logs,tools} \
         train/lines/27b-kittyrev/{base,local-pack,data,quant,merged,heretic-pareto} \
         train/lines/_shared/{data,logs,hf,tools}

echo "== 3) 真实移动（同盘 rename，秒级）=="
mv1(){ if [ -e "$1" ]; then mv "$1" "$2" && echo "mv $1 → $2"; else echo "skip(缺) $1"; fi; }
# 9B
mv1 train/lines/9b-oxcoder/models            train/lines/9b-oxcoder/models
mv1 train/lines/9b-oxcoder/out               train/lines/9b-oxcoder/out
mv1 train/lines/9b-oxcoder/data/kitty-reverse train/lines/9b-oxcoder/data/kitty-reverse
mv1 train/lines/9b-oxcoder/data/agent-traj    train/lines/9b-oxcoder/data/agent-traj
mv1 train/lines/9b-oxcoder/data/nsfw-gated    train/lines/9b-oxcoder/data/nsfw-gated
mv1 train/lines/9b-oxcoder/data/nsfw-gated-v1 train/lines/9b-oxcoder/data/nsfw-gated-v1
mv1 train/lines/9b-oxcoder/data/eval          train/lines/9b-oxcoder/data/eval
mv1 train/lines/9b-oxcoder/data/_chunk-audit  train/lines/9b-oxcoder/data/_chunk-audit
mv1 train/eval               train/lines/9b-oxcoder/eval
# 27B
mv1 train/lines/27b-kittyrev/base              train/lines/27b-kittyrev/base
mv1 train/lines/27b-kittyrev/local-pack        train/lines/27b-kittyrev/local-pack
mv1 train/lines/27b-kittyrev/data/versions     train/lines/27b-kittyrev/data/versions
mv1 train/lines/27b-kittyrev/kitty-rev         train/lines/27b-kittyrev/kitty-rev
mv1 train/lines/27b-kittyrev/quant             train/lines/27b-kittyrev/quant
mv1 train/lines/27b-kittyrev/merged            train/lines/27b-kittyrev/merged
mv1 train/lines/27b-kittyrev/heretic-pareto    train/lines/27b-kittyrev/heretic-pareto
# 共享
mv1 train/lines/_shared/data/nsfw         train/lines/_shared/data/nsfw
mv1 train/lines/_shared/data/raw          train/lines/_shared/data/raw
mv1 train/lines/_shared/scripts           train/lines/_shared/scripts
mv1 train/lines/_shared/hf                train/lines/_shared/hf
mv1 train/lines/_shared/tools             train/lines/_shared/tools

echo "== 4) 剩余目录 =="
ls -d train/*/ 2>/dev/null | tr '\n' ' '; echo
ls -d train/data/*/ 2>/dev/null | tr '\n' ' '; echo
df -h /d | tail -1
