#!/usr/bin/env bash
# RE 腿回归：验证 z-re-v4/final 是否仍在 manifest 声明的能力区间内
# 依据：train/lines/9b-oxcoder/DEPLOY-RE-MANIFEST.md
# 用法：
#   bash _work/regress_re.sh            # 完整回归（约 30 min）
#   bash _work/regress_re.sh --check    # 只校验哈希与依赖，不跑评测
set -u
cd /d/BaiduNetdiskDownload/Local-AI || exit 1

PY=./train/.venv/Scripts/python.exe
D=train/lines/9b-oxcoder
AD=$D/out/z-re-v4/final
EVAL=train/lines/_shared/scripts/eval_re_deploy.py
OUTL=$D/out
WANT_SHA=016c1e56a724c9b232009c103c6195748d1a7a013fee89f8e4545324ef5ad1fe

# 阈值（来自 manifest §5）
TH_E1=30
TH_E2_MEAN=31
TH_E3=29

echo "=================================================================="
echo "RE 腿回归  $(date '+%F %T')"
echo "=================================================================="

# ── 1 哈希校验 ──────────────────────────────────────────────────────
if [ ! -f "$AD/adapter_model.safetensors" ]; then
  echo "[FAIL] adapter 不存在：$AD/adapter_model.safetensors"
  exit 2
fi
ACT_SHA=$(sha256sum "$AD/adapter_model.safetensors" | awk '{print $1}')
if [ "$ACT_SHA" != "$WANT_SHA" ]; then
  echo "[FAIL] adapter 哈希不符"
  echo "       期望 $WANT_SHA"
  echo "       实际 $ACT_SHA"
  echo "       → 权重被替换或损坏，manifest §2 的 81% 口径已失效"
  exit 2
fi
echo "[OK]   adapter sha256 与 manifest 一致"

for p in "$D/models/OxCoder-9B/config.json" "$EVAL" \
         train/lines/_shared/scripts/re_clusters.py \
         train/lines/_shared/scripts/eval_cases_re.py; do
  [ -e "$p" ] || { echo "[FAIL] 缺依赖：$p"; exit 2; }
done
echo "[OK]   依赖齐备（基座 config / 评测脚本 / 簇定义 / 40 条用例）"

USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
echo "[INFO] 当前显存占用 ${USED:-?} MiB（>1500 说明有别的进程，可能 OOM）"

if [ "${1:-}" = "--check" ]; then
  echo
  echo "[DRY] 仅校验模式，未跑评测。完整回归：bash _work/regress_re.sh"
  exit 0
fi

# ── 2 跑评测 ────────────────────────────────────────────────────────
run_modes() {  # run_modes <out名> <参数...>；产物缺失即判失败
  local outn="$1"; shift
  echo
  echo "──────── $outn ────────"
  $PY "$EVAL" --adapter "$AD" --out "$OUTL/$outn.json" "$@" 2>&1 \
    | grep -E "^  → \[E[123]\]|^  E[123] 判据|^  ★|^  形态判定|\
Traceback|Error|error:|OSError|RuntimeError|CUDA|OutOfMemory|页面文件|1455"
  if [ ! -f "$OUTL/$outn.json" ]; then
    echo "  [FAIL] 本次评测未产出 $outn.json —— 看上面的报错（内存/显存/参数）"
    return 1
  fi
  return 0
}

RC_A=0; RC_B=0
run_modes "regress-e1e2e3-s7" --modes e1,e2,e3 --seed 7   || RC_A=1
run_modes "regress-e2-s11"    --modes e2      --seed 11   || RC_B=1

# ── 3 汇总判定 ──────────────────────────────────────────────────────
echo
echo "=================================================================="
echo "判定"
echo "=================================================================="
$PY - "$OUTL" "$TH_E1" "$TH_E2_MEAN" "$TH_E3" <<'PYEOF'
import glob, io, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
OUTL, TH_E1, TH_E2M, TH_E3 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])

def get(path, mode):
    if not os.path.exists(path):
        return None
    d = json.load(io.open(path, encoding="utf-8"))["results"]
    return d.get(mode)

a = os.path.join(OUTL, "regress-e1e2e3-s7.json")
b = os.path.join(OUTL, "regress-e2-s11.json")
e1 = get(a, "e1")
e2s7 = get(a, "e2")
e3 = get(a, "e3")
e2s11 = get(b, "e2")

rows = []
if e1:
    rows.append(("E1 无候选集", e1["hit"], TH_E1, e1["hit"] >= TH_E1))
if e2s7 and e2s11:
    mean = (e2s7["hit"] + e2s11["hit"]) / 2.0
    rows.append(("E2 候选集均值(seed7+11)", mean, TH_E2M, mean >= TH_E2M))
elif e2s7:
    # 缺 seed11：不再降级放行，直接判 FAIL（否则「换种子就掉」这一场景会被漏掉）
    rows.append(("E2 候选集(仅 seed7, 缺 seed11)", e2s7["hit"], TH_E2M, False))
if e3:
    rows.append(("E3 干扰档", e3["hit"], TH_E3, e3["hit"] >= TH_E3))

print("  %-26s %-10s %-8s %s" % ("项", "实测", "阈值", "结果"))
print("  " + "-" * 60)
ok = True
for name, val, th, passed in rows:
    v = ("%.1f" % val) if isinstance(val, float) else str(val)
    print("  %-26s %-10s ≥%-7d %s" % (name, v, th, "PASS" if passed else "FAIL"))
    ok = ok and passed

# 编造硬指标
fake = sum((r or {}).get("fake", 0) for r in (e1, e2s7, e3, e2s11))
print("  %-26s %-10d %-8s %s" % ("编造合计", fake, "=0", "PASS" if fake == 0 else "FAIL"))
ok = ok and fake == 0

print()
if ok:
    print("  【回归 PASS】能力仍在 manifest 区间内（81% ± 2.5pt）")
else:
    print("  【回归 FAIL】")
    print("    → 先查 manifest §6 改动即失效清单，确认哪个变量变了")
    print("    → 若是 adapter/基座被替换：从备份恢复 z-re-v4/final（哈希见 §1）")
    print("    → 若是 system/候选集规则被改：按 §3/§4 逐字还原")
sys.exit(0 if ok else 1)
PYEOF
RC=$?
echo
echo "回归退出码 $RC  （0=PASS 1=FAIL 2=前置校验失败）"
exit $RC
