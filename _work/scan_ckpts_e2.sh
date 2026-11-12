#!/usr/bin/env bash
# V2 训练收口后：扫全部 checkpoint 的 E2（部署档），挑最优再跑全套
# 用法：bash _work/scan_ckpts_e2.sh
# 前提：GPU 空闲（训练进程已退出）
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1
PY=./train/.venv/Scripts/python.exe
D=train/lines/9b-oxcoder
OUT=$D/out/z-re-v2-cand
EVAL=train/lines/_shared/scripts/eval_re_deploy.py

echo "=================================================================="
echo "E2 部署档 checkpoint 扫描   $(date '+%F %T')"
echo "=================================================================="
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
echo "当前显存占用 ${used:-?} MiB（>1500 说明还有进程，可能 OOM）"
echo

for tag in checkpoint-400 checkpoint-800 checkpoint-1200 checkpoint-1600 final; do
  p="$OUT/$tag"
  if [ ! -d "$p" ]; then
    echo "[skip] $tag 不存在"
    continue
  fi
  echo "──────── $tag ────────"
  $PY "$EVAL" --adapter "$p" --modes e2 \
      --out "$D/out/eval-e2-$tag.json" 2>&1 \
    | grep -E "^  → \[E2\]|^  E2 判据|^  ★|^  → train" | sed 's/^/  /'
  echo
done

echo "=================================================================="
echo "汇总（按 E2 命中降序）"
echo "=================================================================="
$PY - <<'PYEOF'
import glob, io, json, sys
sys.stdout.reconfigure(encoding="utf-8")
rows = []
for p in sorted(glob.glob("train/lines/9b-oxcoder/out/eval-e2-*.json")):
    d = json.load(io.open(p, encoding="utf-8"))
    r = d["results"].get("e2")
    if not r:
        continue
    tag = p.split("eval-e2-")[-1].replace(".json", "")
    rows.append((r["hit"], tag, r["noarg"], r["wrong"], r["fake"], r["none"],
                 r["by_level"]))
rows.sort(reverse=True)
print("  %-18s %-10s %-7s %-6s %-6s %-6s %s" % ("checkpoint", "命中", "参数错", "选错", "编造", "回避", "L1/L2/L3"))
for hit, tag, na, wr, fk, no, lv in rows:
    s = "/".join("%d/%d" % (lv.get(k, {}).get("hit", 0), lv.get(k, {}).get("n", 0))
                 for k in ("L1", "L2", "L3"))
    print("  %-18s %2d/40     %-7d %-6d %-6d %-6d %s" % (tag, hit, na, wr, fk, no, s))
if rows:
    best = rows[0]
    print()
    print("  最优：%s（%d/40）→ 用它跑全套 E1/E3：" % (best[1], best[0]))
    print("    ./train/.venv/Scripts/python.exe train/lines/_shared/scripts/eval_re_deploy.py \\")
    print("      --adapter train/lines/9b-oxcoder/out/z-re-v2-cand/%s" % best[1])
PYEOF
