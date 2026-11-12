#!/usr/bin/env bash
# mix-v8 训后：多 checkpoint 评测 + 机制门禁 + 选优 → 2A-ACCEPTANCE-MIXV8.md
#
# 与 v5 版的差别（v5 版有两个教训，这里都修掉）：
#   ① 选优只判 acc≥0.65 ⇒ 与「三条件」自相矛盾。这版统一用 RE 三条件。
#   ② 不看机制指纹 ⇒ v5 的 40% tool_call 泄漏被聚合指标摊平。这版每个候选都过 check_eval_gate。
#
# 候选：ckpt-4000 / ckpt-5200 / final（存在才纳入）
# 用法：bash train/lines/_shared/scripts/post_train_mix_v8.sh
set -u
cd "$(dirname "$0")/../.." || exit 1

OUT=train/lines/9b-oxcoder/out/mix-v8
FIN="$OUT/final/adapter_model.safetensors"
LOG=train/logs/mix-v8-post-train.log
PY=train/.venv/Scripts/python.exe
BASE2A=train/lines/9b-oxcoder/out/eval-2a-r3-v2.json
export PYTHONIOENCODING=utf-8
mkdir -p train/logs

echo "[$(date '+%H:%M:%S')] 守候 $FIN" >> "$LOG"
for i in $(seq 1 960); do
  [ -f "$FIN" ] && { echo "[$(date '+%H:%M:%S')] final 已生成" >> "$LOG"; break; }
  [ $((i % 40)) -eq 0 ] && echo "[$(date '+%H:%M:%S')] try=$i step=$(tail -1 "$OUT/train-log.jsonl" 2>/dev/null | sed -n 's/.*"step": *\([0-9]*\).*/\1/p')" >> "$LOG"
  sleep 30
done
[ -f "$FIN" ] || { echo "[$(date '+%H:%M:%S')] 超时" >> "$LOG"; exit 2; }

echo "[$(date '+%H:%M:%S')] 等显存释放" >> "$LOG"
for j in $(seq 1 90); do
  U=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' \r')
  [ -n "$U" ] && [ "$U" -lt 3000 ] 2>/dev/null && { echo "[$(date '+%H:%M:%S')] 已释放 ${U}MiB" >> "$LOG"; break; }
  sleep 5
done
sleep 15

LABELS=(); PATHS=()
add_if() { [ -f "$2/adapter_model.safetensors" ] && { LABELS+=("$1"); PATHS+=("$2"); echo "[$(date '+%H:%M:%S')] 候选 $1 -> $2" >> "$LOG"; }; }
add_if "mixv8-4000" "$OUT/checkpoint-4000"
add_if "mixv8-5200" "$OUT/checkpoint-5200"
add_if "mixv8-final" "$OUT/final"
[ ${#LABELS[@]} -eq 0 ] && { echo "[FATAL] 无可用 adapter" >> "$LOG"; exit 3; }

# ① 2A 评测（每个候选 40 条，max_new 1200 与基线同尺）
for k in "${!LABELS[@]}"; do
  L=${LABELS[$k]}; P=${PATHS[$k]}
  echo "[$(date '+%H:%M:%S')] 2A 评测 $L" >> "$LOG"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$P" --max-new 1200 \
      --out "train/lines/9b-oxcoder/out/eval-2a-$L.json" >> "$LOG" 2>&1
  echo "[$(date '+%H:%M:%S')] 2A $L rc=$?" >> "$LOG"
done

# ② RE 回归（r3 + 全部候选）
SPEC="r3=train/lines/9b-oxcoder/out/re-stage1-r3/final"
for k in "${!LABELS[@]}"; do SPEC="$SPEC,${LABELS[$k]}=${PATHS[$k]}"; done
echo "[$(date '+%H:%M:%S')] RE 回归 $SPEC" >> "$LOG"
"$PY" train/lines/_shared/scripts/eval_multi_adapter.py --adapters "$SPEC" --max-new 300 --batch 1 \
    --out train/lines/9b-oxcoder/out/eval-re-regress-mixv8.json >> "$LOG" 2>&1
echo "[$(date '+%H:%M:%S')] RE rc=$?" >> "$LOG"

# ③ 机制门禁（每个候选都过；v5 的 40% tool_call 就是被这条拦的）
for L in "${LABELS[@]}"; do
  echo "" >> "$LOG"
  echo "----- check_eval_gate $L -----" >> "$LOG"
  "$PY" train/lines/_shared/scripts/check_eval_gate.py "train/lines/9b-oxcoder/out/eval-2a-$L.json" --base "$BASE2A" >> "$LOG" 2>&1
  echo "[$(date '+%H:%M:%S')] gate $L rc=$?" >> "$LOG"
done

# ④ 汇总（RE 三条件 + 2A + tool_call 率）
"$PY" - "${LABELS[@]}" << 'PYEOF' >> "$LOG" 2>&1
import io, json, os, re, sys

T = "train"
labels = sys.argv[1:]
L = []
def say(s=""):
    print(s); L.append(s)
def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.isfile(p) else None
TCALL = re.compile(r"<tool_call>|<tool_response>")

c2a, re_all, tc_rate = {}, {}, {}
for lb in labels:
    d = load(os.path.join(T, "out", "eval-2a-%s.json" % lb))
    if d:
        c2a[lb] = d
        det = d.get("detail") or []
        tc_rate[lb] = (sum(1 for r in det if TCALL.search(str(r.get("resp_head") or ""))) / len(det)) if det else 0.0
rd = load(os.path.join(T, "out", "eval-re-regress-mixv8.json"))
if rd:
    re_all = {r["label"]: r for r in rd["results"]}

say("=" * 88)
say("mix-v8 验收（kitty 23674 清理版 + 2A lite 848 · 6131 步 · 2026-10-30）")
say("=" * 88)
say("")
say("── 一、2A（40 条 · max_new 1200 · 与基线同尺）──")
say("  %-14s %8s %10s %9s %10s %8s" % ("adapter", "avg_cov", "code_rate", "ngram20", "tool_call", "判定"))
say("  %-14s %7.1f%% %9.1f%% %9.3f %9s %8s" % ("r3（基线）", 60.0, 40.0, 0.0, "10.0%", "PASS"))
for lb in labels:
    d = c2a.get(lb)
    if not d:
        say("  %-14s [缺]" % lb); continue
    ok = d["avg_cov"] >= 0.60 and d["code_rate"] >= 0.40
    say("  %-14s %7.1f%% %9.1f%% %9.3f %9.1f%% %8s"
        % (lb, 100 * d["avg_cov"], 100 * d["code_rate"], d.get("avg_ngram20", 0),
           100 * tc_rate.get(lb, 0), "PASS" if ok else "FAIL"))
say("  判据：cov>=60% 且 code>=40%；tool_call 率须 <=10%（v5 是 40%，是它翻车的机制指纹）")

if re_all:
    say("")
    say("── 二、RE 回归（40 条 · 同尺同参 · 三条件）──")
    say("  %-14s %4s %6s %5s %5s %8s %9s" % ("label", "hit", "参数错", "选错", "编造", "acc", "三条件"))
    for lb, r in re_all.items():
        acc, na, fk = r.get("acc", 0), r.get("noarg", 99), r.get("fake", 99)
        ok3 = acc >= 0.65 and na <= 5 and fk == 0
        say("  %-14s %4d %6d %5d %5d %7.1f%% %9s"
            % (lb, r.get("hit", 0), na, r.get("wrong", 0), fk, 100 * acc, "PASS" if ok3 else "FAIL"))

say("")
say("── 三、选优（RE 三条件 + 2A 双指标 + tool_call<=10% 四条同时成立）──")
cands = []
for lb in labels:
    if lb not in c2a or lb not in re_all:
        continue
    r = re_all[lb]
    acc, na, fk = r.get("acc", 0), r.get("noarg", 99), r.get("fake", 99)
    d = c2a[lb]
    ok_re = acc >= 0.65 and na <= 5 and fk == 0
    ok_2a = d["avg_cov"] >= 0.60 and d["code_rate"] >= 0.40
    ok_tc = tc_rate.get(lb, 1) <= 0.10
    cands.append((lb, d["avg_cov"], d["code_rate"], acc, tc_rate.get(lb, 1), ok_re, ok_2a, ok_tc))
if cands:
    for c in cands:
        say("  %-14s cov %5.1f%% code %5.1f%% RE %5.1f%% tc %5.1f%%  RE:%s 2A:%s TC:%s"
            % (c[0], 100 * c[1], 100 * c[2], 100 * c[3], 100 * c[4],
               "P" if c[5] else "F", "P" if c[6] else "F", "P" if c[7] else "F"))
    full = [c for c in cands if c[5] and c[6] and c[7]]
    say("")
    if full:
        best = sorted(full, key=lambda x: (-x[2], -x[1]))[0]
        say("  推荐交付：**%s**（四条判据全过）" % best[0])
    else:
        # 逐条说明差在哪
        best = sorted(cands, key=lambda x: (-int(x[5]), -int(x[7]), -x[2], -x[1]))[0]
        say("  无候选四条全过。缺口最小的：**%s**" % best[0])
        miss = []
        if not best[5]: miss.append("RE 三条件")
        if not best[6]: miss.append("2A cov/code")
        if not best[7]: miss.append("tool_call 率")
        say("  差在：%s" % " / ".join(miss))
        if not best[7]:
            say("  ⇒ 工具泄漏仍在（%.1f%%）：说明负例/禁令不足以压住，需要提高 2A 中「禁工具」样本的权重或比例" % (100 * best[4]))
        elif not best[6]:
            say("  ⇒ 工具泄漏已压住（%.1f%%），但 2A 能力仍不足：说明瓶颈转到数据量/质量，而非格式" % (100 * best[4]))

say("")
say("=" * 88)
say("判据来源：TASKPOINT §A1 + mix-v5 缺陷分析（train/logs/mix-v5-FAILURE-ANALYSIS.md）")
say("=" * 88)
io.open(os.path.join(T, "2A-ACCEPTANCE-MIXV8.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n-> train/2A-ACCEPTANCE-MIXV8.md")
PYEOF

echo "[$(date '+%H:%M:%S')] 全部完成" >> "$LOG"
