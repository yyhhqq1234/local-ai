#!/usr/bin/env bash
# negative_item6.sh —— 证明 post_chain.sh 的 P5 struct-align 现在会阻断
# 做法：把 post_chain 的 P5 三行原样抽出，接到"必定 rc=1"的假 verify 上，看是否 exit 1
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
POST="$HERE/post_chain.sh"   # HERE = tools/
SBOX="$HERE/neg6"
rm -rf "$SBOX" 2>/dev/null || true
mkdir -p "$SBOX/ninfer-v4"
printf '#!/usr/bin/env python3\nimport sys\nprint("[fake] struct-align RED: A2 缺 mtp | A4 bytes 不足")\nsys.exit(1)\n' > "$SBOX/fake_align.py"
: > "$SBOX/ninfer-v4/final2.ninfer"     # 空壳产物，只要能跑通流程

# 抽取 post_chain 的 P5 段（log P5 → exit 1 那行）
sed -n '/log "\[P5\] struct-align"/,/\[ \$rc -eq 0 \] ||/p' "$POST" > "$SBOX/p5.sh"
echo "--- 抽出的 P5 段 ---"; cat "$SBOX/p5.sh"

# 装配成可跑片段：替换 log()/路径/脚本
{
  echo '#!/usr/bin/env bash'
  echo 'set -uo pipefail'
  echo "LOG='$SBOX/POST-CHAIN.log'"
  echo 'log(){ echo "$(date "+%F %T") $*" | tee -a "$LOG"; }'
  echo "PY=$(command -v python || echo python)"
  echo "OUT=$SBOX/ninfer-v4/final2.ninfer"
  echo "BAD=$SBOX/fake_align.py"
  sed 's#/root/autodl-tmp/_ra/verify-struct-align.py#"$BAD"#' "$SBOX/p5.sh"
  echo 'log "===== 走到这里说明没阻断（BUG） ====="'
} > "$SBOX/run.sh"
bash "$SBOX/run.sh"; rc=$?
echo "--- 结果 ---"
echo "rc=$rc"; tail -3 "$SBOX/POST-CHAIN.log"
[ "$rc" -eq 1 ] && echo "[NEG6] PASS：struct-align 非零 → 整链 exit 1（阻断生效）" || echo "[NEG6] FAIL：没阻断（rc=$rc）"
