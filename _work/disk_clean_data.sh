#!/usr/bin/env bash
# 废弃训练数据清理（2026-11-03）
# 原则：只删「产物已被取代 / 中间件 / .bak / superseded」，
#       凡是能重建当前四档成品（v4 / r3 / z-2a-v7 / 2b-v4b）的原料一律不碰
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
D=train/lines/9b-oxcoder/data

BEFORE=$(df -m /d | awk 'NR==2{print $4}')
echo "=================================================================="
echo "废弃训练数据清理   D: 可用 ${BEFORE} MiB"
echo "=================================================================="

total=0
delf() {  # delf <文件> <说明>
  local p="$1" note="$2"
  if [ ! -f "$p" ]; then printf "  [skip] %-62s 无\n" "$(basename "$p")"; return; fi
  local sz; sz=$(du -m "$p" 2>/dev/null | awk '{print $1}'); [ -z "$sz" ] && sz=0
  rm -f "$p"
  if [ -f "$p" ]; then printf "  [FAIL] %-62s\n" "$(basename "$p")"
  else printf "  [ok] %-62s -%4s MB  %s\n" "$(basename "$p")" "$sz" "$note"; total=$((total+sz)); fi
}
deld() {  # deld <目录> <说明>
  local p="$1" note="$2"
  if [ ! -e "$p" ]; then printf "  [skip] %-62s 无\n" "$(basename "$p")"; return; fi
  local sz; sz=$(du -sm "$p" 2>/dev/null | awk '{print $1}'); [ -z "$sz" ] && sz=0
  rm -rf "$p"
  if [ -e "$p" ]; then printf "  [FAIL] %-62s\n" "$(basename "$p")"
  else printf "  [ok] %-62s -%4s MB  %s\n" "$(basename "$p")" "$sz" "$note"; total=$((total+sz)); fi
}

echo "[1] 旧配方 mix-2a / mix-2b（已被 mix-z-2a-v7 / mix-z-re-v4 取代）"
delf $D/_legacy/mix-2a.jsonl              "2A 第一版"
delf $D/_legacy/mix-2a-bucketed.jsonl     "2A 第一版桶化"
delf $D/_legacy/mix-2b.jsonl              "2B 旧版（AGENTS 明示废弃）"
delf $D/_legacy/mix-2b-bucketed.jsonl     "2B 旧版桶化"

echo "[2] mix-2c 中间件（2C 长上下文尚未开始，原料 mix-2c.jsonl / mix-2c-gated.jsonl 保留）"
delf $D/_legacy/mix-2c-gated.jsonl.bak-dedup  "去重前备份"
delf $D/_legacy/mix-2c-gated-bucketed.jsonl   "桶化中间件"
delf $D/_legacy/mix-2c-bucketed.jsonl         "桶化中间件"

echo "[3] v5-v8 四轮加数据实验（已实证净收益 ≤0，数据已并入 v4）"
for f in mix-v5 mix-v6 mix-v7 mix-v8; do delf "$D/_legacy/$f.jsonl" "退步实验数据"; done

echo "[4] RE/2A 历史版本（定稿版 v4 / v4-fixed / z-2a-v7 保留）"
for f in mix-z-re mix-z-re-v3 mix-z-re-v8 mix-z-re-v8b; do delf "$D/_legacy/$f.jsonl" "历史版本"; done
for f in mix-z-2a mix-z-2a-v3 mix-z-2a-v5 mix-z-2a-v6; do delf "$D/_legacy/$f.jsonl" "2A 历史版本"; done

echo "[5] superseded-20261101（目录名即废弃）"
deld $D/_legacy/superseded-20261101 "已取代归档"

echo "[6] agent-traj 旧版（traj-all / traj-2a-v4 / -v4-aug 保留）"
delf $D/agent-traj/traj-all-capped.jsonl.bak-dedup "去重前备份"
delf $D/agent-traj/traj-2a-v2.jsonl                "v2 旧版"
delf $D/agent-traj/traj-2a-v2-bucketed.jsonl       "v2 旧版桶化"
delf $D/agent-traj/traj-2a-v2-2048-bucketed.jsonl  "v2 旧版桶化"
delf $D/agent-traj/traj-2a-v3-clean.jsonl          "v3 历史"

echo "[7] nsfw-gated 历史版与废弃版（v4b 母版 + deleak 训练版保留）"
delf $D/nsfw-gated/train-2b-gated-v3.jsonl         "v3 历史"
delf $D/nsfw-gated/train-2b-gated-v3b.jsonl        "v3b 历史"
delf $D/nsfw-gated/train-2b-gated-v4.jsonl         "v4 泄漏版（已废）"
delf $D/nsfw-gated/train-2b-gated-v4-train.jsonl   "v4 泄漏版训练分割"
delf $D/nsfw-gated/train-2b-gated-v4b-train.jsonl  "v4b 旧训练版（已被 deleak 取代）"
delf $D/nsfw-gated/train-2b-gated.jsonl            "v1 旧版"
delf $D/nsfw-gated/train-2b-gated.jsonl.bak-toolclean "v1 备份"

echo "[8] kitty-reverse 备份与已并入的增量"
delf $D/kitty-reverse/train-kitty-core.jsonl.bak-typo  "改名前备份"
delf $D/kitty-reverse/train-kitty-v2-aug.jsonl.bak-dedup "去重前备份"

AFTER=$(df -m /d | awk 'NR==2{print $4}')
echo "=================================================================="
echo "释放 ${total} MB   D: ${BEFORE} -> ${AFTER} MiB（净增 $((AFTER-BEFORE)) MiB）"
echo "=================================================================="

echo
echo "===== 保护项复核（能重建四档成品的数据必须都在）====="
for keep in \
  $D/eval \
  $D/_legacy/mix-z-re-v4.jsonl \
  $D/_legacy/mix-z-re-v4-fixed.jsonl \
  $D/_legacy/mix-z-2a-v7.jsonl \
  $D/_legacy/mix-2c.jsonl \
  $D/_legacy/mix-2c-gated.jsonl \
  $D/nsfw-gated/train-2b-gated-v4b.jsonl \
  $D/nsfw-gated/train-2b-gated-v4b-train-deleak.jsonl \
  $D/agent-traj/traj-all.jsonl \
  $D/agent-traj/traj-2a-v4.jsonl \
  $D/agent-traj/traj-2a-v4-aug.jsonl \
  $D/kitty-reverse/train-kitty-v3-clean.jsonl \
  $D/kitty-reverse/kitty-contracts ; do
  if [ -e "$keep" ]; then printf "  OK   %-70s %s\n" "$(basename "$keep")" "$(du -sh "$keep" 2>/dev/null | awk '{print $1}')"
  else printf "  MISS %-70s ★异常\n" "$(basename "$keep")"; fi
done
