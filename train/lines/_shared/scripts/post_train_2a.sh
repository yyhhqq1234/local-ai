#!/usr/bin/env bash
# 2A 训练结束 → 自动双评测 → 对照报告（无人值守）
#
# 触发：train/lines/9b-oxcoder/out/2a-stage/final/adapter_model.safetensors 出现
#
# 输出：
#   train/lines/9b-oxcoder/out/eval-2a-final.json        2A 40 条（编程轨迹）
#   train/lines/9b-oxcoder/out/eval-re-regress.json      RE 40 条回归（r3 vs 2a）
#   train/2A-ACCEPTANCE.md              对照报告
#   train/logs/2a-post-train.log        全过程日志
#
# 为什么要双评测：
#   2A 训的是编程能力，但 2A 用 --init-adapter 从 r3 续训，
#   有把 kitty 工具能力冲掉的真实风险（r2 的 3 遍就出现过能力退化）。
#   所以必须同时看：2A 有没有变好 + RE 有没有被冲坏。
set -u
cd "$(dirname "$0")/../.." || exit 1

OUT=train/lines/9b-oxcoder/out/2a-stage
FIN="$OUT/final/adapter_model.safetensors"
LOG=train/logs/2a-post-train.log
PY=train/.venv/Scripts/python.exe
mkdir -p train/logs

echo "[$(date +%H:%M:%S)] 开始守候 $FIN" >> "$LOG"

# ── 1 守候训练结束（最多 20 h，每 30 s）────────────────────────
for i in $(seq 1 2400); do
  if [ -f "$FIN" ]; then
    echo "[$(date +%H:%M:%S)] 训练完成，final 已生成" >> "$LOG"
    break
  fi
  if [ $((i % 20)) -eq 0 ]; then
    STEP=$(tail -1 "$OUT/train-log.jsonl" 2>/dev/null | sed -n 's/.*"step": *\([0-9]*\).*/\1/p')
    echo "[$(date +%H:%M:%S)] 守候中 try=$i step=${STEP:-?}" >> "$LOG"
  fi
  sleep 30
done

if [ ! -f "$FIN" ]; then
  echo "[$(date +%H:%M:%S)] 超时未等到 final，退出" >> "$LOG"
  exit 2
fi

# ── 2 等显存释放（同 r3 的加固：训练进程收尾要 10-30 s）────────
echo "[$(date +%H:%M:%S)] 等显存释放" >> "$LOG"
for j in $(seq 1 90); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' \r')
  if [ -n "$USED" ] && [ "$USED" -lt 3000 ] 2>/dev/null; then
    echo "[$(date +%H:%M:%S)] 显存已释放 used=${USED}MiB" >> "$LOG"
    break
  fi
  sleep 5
done
sleep 10

# ── 3 2A 评测（40 条编程任务）────────────────────────────────
echo "[$(date +%H:%M:%S)] 启动 2A 评测（40 条）" >> "$LOG"
$PY train/lines/_shared/scripts/eval_2a_code.py \
    --adapter train/lines/9b-oxcoder/out/2a-stage/final \
    --max-new 1200 \
    --out train/lines/9b-oxcoder/out/eval-2a-final.json >> "$LOG" 2>&1
echo "[$(date +%H:%M:%S)] 2A 评测结束 rc=$?" >> "$LOG"

# ── 4 RE 回归（r3 vs 2a，r3 档走缓存秒回）────────────────────
echo "[$(date +%H:%M:%S)] 启动 RE 回归（r3 vs 2a）" >> "$LOG"
$PY train/lines/_shared/scripts/eval_multi_adapter.py \
    --adapters "r3=train/lines/9b-oxcoder/out/re-stage1-r3/final,2a=train/lines/9b-oxcoder/out/2a-stage/final" \
    --max-new 300 --batch 1 \
    --out train/lines/9b-oxcoder/out/eval-re-regress.json >> "$LOG" 2>&1
echo "[$(date +%H:%M:%S)] RE 回归结束 rc=$?" >> "$LOG"

# ── 5 汇总对照 ────────────────────────────────────────────────
PYTHONIOENCODING=utf-8 $PY - << 'PYEOF' >> "$LOG" 2>&1
import json, io, os

T = "train"
lines = []
def say(s=""):
    print(s); lines.append(s)

say("=" * 78)
say("2A 验收对照（2026-10-29）")
say("=" * 78)

# 2A
p2a = os.path.join(T, "out", "eval-2a-final.json")
if os.path.isfile(p2a):
    d = json.load(io.open(p2a, encoding="utf-8"))
    say("")
    say("── 一、2A 编程轨迹（40 条，训后）──")
    say("  实体覆盖率   %.1f%%   （训前基线 60.0%%，目标 >=70%%）" % (d["avg_cov"] * 100))
    say("  代码块完整率 %.1f%%   （训前基线 40.0%%，目标 >=60%%）" % (d["code_rate"] * 100))
    say("  参考相似度   %.3f   （仅报告）" % d["avg_ngram20"])
    ok_cov = d["avg_cov"] >= 0.70
    ok_code = d["code_rate"] >= 0.60
    say("  判定：覆盖 %s | 代码 %s" % ("✅" if ok_cov else "❌", "✅" if ok_code else "❌"))
else:
    ok_cov = ok_code = False
    say("  [缺] %s 不存在" % p2a)

# RE 回归
pre = os.path.join(T, "out", "eval-re-regress.json")
ok_re = False
if os.path.isfile(pre):
    d = json.load(io.open(pre, encoding="utf-8"))
    say("")
    say("── 二、RE 回归（40 条 kitty 口径，看有没有被 2A 冲坏）──")
    say("  %-8s %5s %6s %6s %6s %5s %7s" % ("label", "hit", "参数错", "选错", "编造", "回避", "acc"))
    for r in d.get("results") or []:
        say("  %-8s %5d %6d %6d %6d %5d %7.1f%%"
            % (r.get("label"), r.get("hit", 0), r.get("noarg", 0), r.get("wrong", 0),
               r.get("fake", 0), r.get("none", 0), 100 * r.get("acc", 0)))
    t2a = next((r for r in d.get("results") or [] if r.get("label") == "2a"), None)
    if t2a:
        ok_re = t2a.get("acc", 0) >= 0.70 and t2a.get("noarg", 99) <= 5 and t2a.get("fake", 99) == 0
        say("  判定（2a 档：命中>=70%% 且 参数错<=5 且 编造=0）：%s"
            % ("✅ 未退化" if ok_re else "❌ 被冲坏"))
else:
    say("  [缺] %s 不存在" % pre)

say("")
say("=" * 78)
allok = ok_cov and ok_code and ok_re
say("总判定：%s" % ("✅ 2A 通过且 RE 未退化" if allok else "❌ 未通过，见上"))
say("=" * 78)

io.open(os.path.join(T, "2A-ACCEPTANCE.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n→ 报告 train/2A-ACCEPTANCE.md")
PYEOF

echo "[$(date +%H:%M:%S)] 全部完成" >> "$LOG"
