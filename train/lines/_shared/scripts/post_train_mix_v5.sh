#!/usr/bin/env bash
# mix-v5 训练结束 → 多 checkpoint 双评测 → 选优 → 验收报告（无人值守）
#
# 为什么要多 checkpoint（2026-10-30 11:09 改）：
#   训练到 step 4000 后 watch 打出 RED（min 0.0723<0.090 / 单窗 <0.105 两条）。
#   查实的机制：**kitty 段在本轮是第 2 遍曝光**（r3 已训过 1 遍 + 本轮 1 遍），
#   所以它的 loss 地板必然低于 r3 单遍的 0.1596 —— 这是 rehearsal 的算术后果，不是异常。
#   但"第 2 遍 + lr 衰减期"确实可能把 RE 能力磨坏，而这只能靠评测回答。
#   ⇒ 因此保留全部 checkpoint，训后按 RE 与 2A 双指标**选**，而不是盲取 final。
#
# 评测对象：r3（基线，缓存秒回）/ mixv5-4000 / mixv5-5200（存在才算）/ mixv5-final
#   —— 4000 是 RED 出现的位置，final 是"跑满一遍"的位置，两个都测才知道后半程是损是益。
#
# 用法：bash train/lines/_shared/scripts/post_train_mix_v5.sh
set -u
cd "$(dirname "$0")/../.." || exit 1

OUT=train/lines/9b-oxcoder/out/mix-v5
FIN="$OUT/final/adapter_model.safetensors"
LOG=train/logs/mix-v5-post-train.log
PY=train/.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8          # F4：Windows stdout 是 cp936
mkdir -p train/logs

echo "[$(date '+%H:%M:%S')] 开始守候 $FIN" >> "$LOG"

# ── 1 守候训练结束（最多 8 h，每 30 s）────────────────────────
for i in $(seq 1 960); do
  if [ -f "$FIN" ]; then
    echo "[$(date '+%H:%M:%S')] 训练完成，final 已生成" >> "$LOG"
    break
  fi
  if [ $((i % 40)) -eq 0 ]; then
    STEP=$(tail -1 "$OUT/train-log.jsonl" 2>/dev/null | sed -n 's/.*"step": *\([0-9]*\).*/\1/p')
    echo "[$(date '+%H:%M:%S')] 守候中 try=$i step=${STEP:-?}" >> "$LOG"
  fi
  sleep 30
done

if [ ! -f "$FIN" ]; then
  echo "[$(date '+%H:%M:%S')] 超时未等到 final，退出" >> "$LOG"
  exit 2
fi

# ── 2 等显存释放（收尾要 10-30 s；WDDM 释放有延迟）──────────────
echo "[$(date '+%H:%M:%S')] 等显存释放" >> "$LOG"
for j in $(seq 1 90); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' \r')
  if [ -n "$USED" ] && [ "$USED" -lt 3000 ] 2>/dev/null; then
    echo "[$(date '+%H:%M:%S')] 显存已释放 used=${USED}MiB" >> "$LOG"
    break
  fi
  sleep 5
done
sleep 15

# ── 3 组装待测 adapter 清单（只收存在且非空的）──────────────────
LABELS=(); PATHS=()
add_if() {                      # $1=label  $2=dir
  if [ -f "$2/adapter_model.safetensors" ]; then
    LABELS+=("$1"); PATHS+=("$2")
    echo "[$(date '+%H:%M:%S')] 纳入评测：$1 -> $2" >> "$LOG"
  fi
}
add_if "mixv5-4000" "$OUT/checkpoint-4000"
add_if "mixv5-5200" "$OUT/checkpoint-5200"
add_if "mixv5-final" "$OUT/final"
if [ ${#LABELS[@]} -eq 0 ]; then
  echo "[$(date '+%H:%M:%S')] [FATAL] 没有任何可用 adapter" >> "$LOG"; exit 3
fi

# ── 4 2A 编程轨迹评测（每个 adapter 40 条）────────────────────
for k in "${!LABELS[@]}"; do
  L=${LABELS[$k]}; P=${PATHS[$k]}
  echo "[$(date '+%H:%M:%S')] 2A 评测 $L" >> "$LOG"
  "$PY" train/lines/_shared/scripts/eval_2a_code.py --adapter "$P" --max-new 1200 \
      --out "train/lines/9b-oxcoder/out/eval-2a-$L.json" >> "$LOG" 2>&1
  echo "[$(date '+%H:%M:%S')] 2A 评测 $L 结束 rc=$?" >> "$LOG"
done

# ── 5 RE 回归（r3 + 全部候选，同尺同参，r3 走缓存）────────────
SPEC="r3=train/lines/9b-oxcoder/out/re-stage1-r3/final"
for k in "${!LABELS[@]}"; do SPEC="$SPEC,${LABELS[$k]}=${PATHS[$k]}"; done
echo "[$(date '+%H:%M:%S')] RE 回归：$SPEC" >> "$LOG"
"$PY" train/lines/_shared/scripts/eval_multi_adapter.py --adapters "$SPEC" \
    --max-new 300 --batch 1 --out train/lines/9b-oxcoder/out/eval-re-regress-mixv5.json >> "$LOG" 2>&1
echo "[$(date '+%H:%M:%S')] RE 回归结束 rc=$?" >> "$LOG"

# ── 6 汇总 + 选优 → train/2A-ACCEPTANCE-MIXV5.md ───────────────
"$PY" - "${LABELS[@]}" << 'PYEOF' >> "$LOG" 2>&1
import io
import json
import os
import sys

T = "train"
labels = sys.argv[1:]
lines = []


def say(s=""):
    print(s)
    lines.append(s)


def load(p):
    return json.load(io.open(p, encoding="utf-8")) if os.path.isfile(p) else None


say("=" * 84)
say("mix-v5 验收（方案 Y：kitty 23718 + 2A 2001 · 6430 步 · 2026-10-30）")
say("=" * 84)

# ── 一、2A 侧
say("")
say("── 一、2A 编程轨迹（40 条）──")
say("  %-14s %9s %10s %10s %8s" % ("adapter", "avg_cov", "code_rate", "ngram20", "判定"))
C2A = {}
for L in labels:
    d = load(os.path.join(T, "out", "eval-2a-%s.json" % L))
    if not d:
        say("  %-14s [缺] eval-2a-%s.json" % (L, L))
        continue
    ok = d["avg_cov"] >= 0.60 and d["code_rate"] >= 0.40
    C2A[L] = (d["avg_cov"], d["code_rate"], ok)
    say("  %-14s %8.1f%% %9.1f%% %10.3f %8s"
        % (L, 100 * d["avg_cov"], 100 * d["code_rate"], d.get("avg_ngram20", 0),
           "PASS" if ok else "FAIL"))
say("  参考：不训练 60.0%/40.0% · 上一轮训坏(2a) 30.6%/2.5% · 判据 >=60% / >=40%")

# ── 二、RE 侧
say("")
say("── 二、RE 回归（kitty 口径 40 条，同尺同参）──")
d = load(os.path.join(T, "out", "eval-re-regress-mixv5.json"))
CRE = {}
CRE_FULL = {}
if d:
    say("  %-14s %5s %7s %6s %6s %5s %8s %8s" % (
        "label", "hit", "参数错", "选错", "编造", "回避", "acc", "判定"))
    for r in d.get("results") or []:
        lb = r.get("label")
        ok = (r.get("acc", 0) >= 0.65 and r.get("noarg", 99) <= 5 and r.get("fake", 99) == 0)
        CRE[lb] = r.get("acc", 0)
        CRE_FULL[lb] = (r.get("acc", 0), r.get("noarg", 99), r.get("fake", 99))
        say("  %-14s %5d %7d %6d %6d %5d %7.1f%% %8s"
            % (lb, r.get("hit", 0), r.get("noarg", 0), r.get("wrong", 0),
               r.get("fake", 0), r.get("none", 0), 100 * r.get("acc", 0),
               "PASS" if ok else "FAIL"))
    base = CRE.get("r3", 0)
    for lb, acc in CRE.items():
        if lb != "r3":
            say("  %-14s 与 r3 差 %+.1fpp（r3 %.1f%% → %.1f%%）"
                % (lb, 100 * (acc - base), 100 * base, 100 * acc))
    say("  判据（§A1）：命中>=65% 且 参数错<=5 且 编造=0")
else:
    say("  [缺] eval-re-regress-mixv5.json")

# ── 三、选优
say("")
say("── 三、选优（RE 是约束，2A 是目标）──")
cands = []
for L in labels:
    if L not in C2A or L not in CRE:
        continue
    cov, code, ok2a = C2A[L]
    acc = CRE[L]
    # ★ 2026-10-30 14:40 修正：原来只判 acc>=0.65，与上表"判定"列（三条件）自相矛盾。
    #   本节一律以 CRE_FULL 的三条件为准（命中>=65% 且 参数错<=5 且 编造=0）。
    okr3, noarg, fake = CRE_FULL.get(L, (0, 99, 99))
    okre = (acc >= 0.65 and noarg <= 5 and fake == 0)
    cands.append((L, cov, code, acc, ok2a, okre))
if not cands:
    say("  无可比候选（评测缺失）")
else:
    cands.sort(key=lambda x: (-int(x[5]), -int(x[4]), -x[2], -x[3], -x[1]))
    best = cands[0]
    for c in cands:
        say("  %-14s cov %.1f%% code %.1f%% RE %.1f%% %s%s"
            % (c[0], 100 * c[1], 100 * c[2], 100 * c[3],
               "2A-PASS " if c[4] else "2A-FAIL ",
               "RE-PASS" if c[5] else "RE-FAIL"))
    say("")
    if best[5] and best[4]:
        say("  推荐：**%s**（RE %.1f%% 未跌破 65%%，2A cov %.1f%% / code %.1f%% 双达标）"
            % (best[0], 100 * best[3], 100 * best[1], 100 * best[2]))
        say("  ⇒ 交付用 %s" % best[0])
    elif best[5]:
        say("  推荐：**%s**（RE 保住 %.1f%%，但 2A 未达标：cov %.1f%% / code %.1f%%）"
            % (best[0], 100 * best[3], 100 * best[1], 100 * best[2]))
        say("  ⇒ 结论写「保 RE 成功、2A 未达成」；下一步走方案 X（70:30）或 Z（双 adapter）")
    else:
        say("  警告：**全部候选都跌破 RE 65%%** —— 8%% rehearsal 也保不住 RE，")
        say("        说明 kitty 第 2 遍曝光（第 2 epoch）已在磨损工具调用能力。")
        say("        ⇒ 回退 r3（train/lines/9b-oxcoder/out/re-stage1-r3/final），本轮判 FAIL。")

say("")
say("=" * 84)
say("验收口径来源：TASKPOINT.md §A1；判据标定依据：train/logs/mix-v5-RUN.md §4.4")
say("=" * 84)

io.open(os.path.join(T, "2A-ACCEPTANCE-MIXV5.md"), "w", encoding="utf-8").write(
    "\n".join(lines) + "\n")
print("\n-> 报告 train/2A-ACCEPTANCE-MIXV5.md")
PYEOF

echo "[$(date '+%H:%M:%S')] 全部完成" >> "$LOG"
