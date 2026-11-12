#!/usr/bin/env bash
# 2A 训练持续监控（脚本级，不依赖 LLM）
#
# 为什么有这个东西：
#   subagent（monitor-2a）每轮汇报完就进入 finished 状态，要人再喊一次才继续。
#   「持续盯」这件事该由脚本做 —— 每 10 分钟采一次样、算健康指标、写一行日志，
#   只在异常时打 ALERT。人/agent 只需要看日志文件。
#
# 输出：train/logs/2a-watch.log（每 10 分钟一行）
# 异常：行首带 [ALERT] 或 [RED]
#
# 启动：bash train/lines/_shared/scripts/watch_2a.sh   （用 run_in_background 起）
set -u
cd "$(dirname "$0")/../.." || exit 1

# 2026-10-30：参数化（env 可覆盖），默认值 = 2A 那一轮的原样，历史行为不变
#   OUT=train/lines/9b-oxcoder/out/mix-v5 LOG=train/logs/mix-v5-watch.log BASE_LT15=0 BASE_LT10=0 BASE_MIN=9 BASE_N=0 HIST_RATE=0.0140845 bash train/lines/_shared/scripts/watch_2a.sh
OUT="${OUT:-train/lines/9b-oxcoder/out/2a-stage}"
LOG="${WATCH_LOG:-train/logs/2a-watch.log}"
export OUT
export WATCH_LOG="$LOG"
export PYTHONIOENCODING=utf-8   # 2026-10-30：否则内联 python 的中文进度行按 cp936 落盘 → 日志 UTF-8/GBK 混杂乱码
PY=train/.venv/Scripts/python.exe
mkdir -p train/logs

echo "[$(date '+%m-%d %H:%M:%S')] watcher 启动，目标 $OUT/final" >> "$LOG"

while true; do
  # 终止条件 1：final 出现
  if [ -f "$OUT/final/adapter_model.safetensors" ]; then
    echo "[$(date '+%m-%d %H:%M:%S')] [DONE] final 已生成，watcher 退出" >> "$LOG"
    break
  fi

  # 采样 + 判定（python 内联）
  "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, io, os, statistics, subprocess, sys, time

OUT = os.environ.get("OUT", "train/lines/9b-oxcoder/out/2a-stage")
rows = []
try:
    for l in io.open(os.path.join(OUT, "train-log.jsonl"), encoding="utf-8"):
        try:
            o = json.loads(l)
            if "loss" in o:
                rows.append(o)
        except Exception:
            pass
except FileNotFoundError:
    print("[%s] [WAIT] train-log.jsonl 未生成" % time.strftime("%m-%d %H:%M:%S"))
    sys.exit(0)

if not rows:
    sys.exit(0)

step = rows[-1]["step"]
loss = rows[-1]["loss"]
recent = [r["loss"] for r in rows[-20:]]        # 近 100 步（logging_steps=5）
grad = [r.get("grad_norm", 0) for r in rows[-20:]]
lt25 = sum(1 for x in recent if x < 0.25)
lt15 = sum(1 for x in recent if x < 0.15)
lt10 = sum(1 for x in recent if x < 0.10)
mean_r = sum(recent) / len(recent)
std_r = statistics.pstdev(recent)
# ── 崩溃恢复基线（2026-10-29 17:29 BugCheck 0x116 VIDEO_TDR_FAILURE 后 resume）──
# --resume 会【覆盖写】train-log.jsonl（568 行 → 3 行）与 mem-trace.jsonl（~2800 → 18 行），
# 崩溃前的逐条 loss 历史丢失。以下基线从 train/logs/2a-watch.log 的 24 个采样点重建：
#   step 1005 0/201 │ 1190 1/238 │ 1365 3/273 │ 1500 5/300 │ 1585 6/317
#   1840 6/368 │ 2015 6/403 │ 2185 7/437 │ 2535 7/507 │ 2620 8/524 │ 2840 8/568（崩溃点）
# 清零会让 lt15 看起来从 0 起算 = 假清白。勿删、勿手改。
BASE_LT15 = int(os.environ.get("BASE_LT15", "8"))
BASE_LT10 = int(os.environ.get("BASE_LT10", "0"))
BASE_MIN = float(os.environ.get("BASE_MIN", "0.1132"))
BASE_N = int(os.environ.get("BASE_N", "560"))          # 崩溃前 568 行 − 约 8 行（2801–2840 会被 resume 重走，避免重复计）
min_all = min(min(r["loss"] for r in rows), BASE_MIN)
n_lt15_all = sum(1 for r in rows if r["loss"] < 0.15) + BASE_LT15
n_lt10_all = sum(1 for r in rows if r["loss"] < 0.10) + BASE_LT10

# ── 相对阈值口径（2026-10-29 18:12 加入，必须与绝对口径并列看）────────────
# 问题：`loss<0.15` 是【固定绝对阈值】，而训练中 mean 会持续下降，
#   固定阈值相当于越来越宽松 —— 左尾条数会自然增长，被误判成记忆化加速。
# 实例：崩溃前 mean=0.3058 std=0.0896 → 0.15 位于 mean−1.739σ；
#       18:12  mean=0.2552 std=0.0698 → 0.15 已移到 mean−1.51σ，左尾自然变宽。
#       绝对口径 12/602=1.99% 看似恶化，相对口径 9/602=1.50%（历史 1.41%）= 持平。
# 做法：锁定崩溃前的相对位置 Z_REF，每次按【当前 mean/std】换算等价阈值。
#   阈值下限压 0.10（绝对地板），防止 mean 降太低时阈值跌破背诵线。
_ZREF = -1.739
_mean_all = sum(r["loss"] for r in rows) / len(rows)
_std_all = statistics.pstdev([r["loss"] for r in rows]) or 1e-9
thr_rel = max(_mean_all + _ZREF * _std_all, 0.10)
n_rel_all = sum(1 for r in rows if r["loss"] < thr_rel) + BASE_LT15
gmean = sum(grad) / len(grad)

# 显存
mem = {}
try:
    last = io.open(os.path.join(OUT, "mem-trace.jsonl"), encoding="utf-8").read().strip().split("\n")[-1]
    mem = json.loads(last)
except Exception:
    pass
alloc = mem.get("alloc_gib", 0)
resv = mem.get("reserved_gib", 0)

# ckpt
cks = []
for d in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
    if d.startswith("checkpoint-"):
        cks.append(int(d.split("-")[1]))
cks.sort()

# GPU（2026-10-29 23:15 改为多点采样）
#   原写法单次瞬时采样，每 10 分钟才取 1 个点 —— 温度平台会被漏掉。
#   实测：watch 记录 >80℃ 只有 1 次(1%)，而 1 秒间隔连采 10 秒显示稳定在 81–82℃。
#   现在采 6 个点（400ms 间隔，约 2.4 秒）：温度/功耗取 MAX 抓峰值，util 取均值。
try:
    pts = []
    for _i in range(5):
        _g = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,power.draw,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip().split(",")
        pts.append([x.strip() for x in _g])
        if _i < 4:
            time.sleep(0.4)
    gpu_used = pts[0][0]
    gpu_util = "%.0f" % (sum(float(p[1]) for p in pts) / len(pts))
    gpu_pw = "%.0f" % max(float(p[2]) for p in pts)
    gpu_t = "%.1f" % max(float(p[3]) for p in pts)
except Exception:
    gpu_used = gpu_util = gpu_pw = gpu_t = "?"

# ── 判定（2026-10-29 第二轮：采纳 monitor-2a 的 T1–T4 硬闸门）────────
#   背景：lt15 出现 1 条就报 RED 会一直红到终点（报警疲劳）。
#   monitor-2a 用「近300步 mean=0.2808 std=0.0633，阈值 0.15 距均值 2.07σ，
#   高斯左尾预期 5.7 条、实测 5 条」证明当前左尾是自然分布、不是记忆化。
#   所以把「lt15≥1」降级为 YEL，只在 T1–T4 触发时打 RED。
flags = []
notes = []   # 旁证：只打印不打 [ALERT]（2026-10-30 引入；相对口径 ltrel 一族全在这里）

# 读上一行日志（用于连续窗判断）
import re as _re
prev = {}
try:
    _lines = io.open(os.environ.get("WATCH_LOG", "train/logs/2a-watch.log"), encoding="utf-8").read().strip().split("\n")
    for _ln in reversed(_lines):
        if "step=" in _ln and "OK" in _ln or "[ALERT]" in _ln:
            for _k in ("lt25", "min"):
                _m = _re.search(r"%s=([\d.]+)" % _k, _ln)
                if _m:
                    prev[_k] = float(_m.group(1))
            break
except Exception:
    pass

# 近 200 步（40 条记录）的 lt15 条数（绝对 + 相对双口径）
r200 = [r["loss"] for r in rows[-40:]]
lt15_200 = sum(1 for x in r200 if x < 0.15)
ltrel_200 = sum(1 for x in r200 if x < thr_rel)
min_cur = min(r["loss"] for r in rows[-20:]) if rows else 9
_min_now = min(r["loss"] for r in rows)
_cv = _std_all / _mean_all if _mean_all > 0 else 0
_ratio = _min_now / _mean_all if _mean_all > 0 else 0

# T1 【2026-10-30 10:0x 三次校准：阈值改为对 r3 自身标定 + 剔除极值】
#   历史：原「lt10>0 → 红」是极值判据，长训练必然触发（E18），已废弃。
#   二代：min/mean<0.30 → 红。**这一代也是错的**，实测依据（calibrate_memorization_threshold.py）：
#     r3（已验收 RE 75.0%，是我们要保住的基线）：全程 min/mean **0.2200**、末 296 点 0.3440
#     ⇒ 合格基线本身就跑在 0.30 以下 ⇒ 0.30 这条红线会把 r3 判成全程记忆化。
#     反向证据：2a（判废那一轮）min/mean 0.4136、lt25 65.5% —— 指标最"健康"的一轮恰是最差的一轮
#     ⇒ min/mean 抓不到"整套样本一起塌"的记忆化，只抓得住"个别样本被压穿"。
#   三代（现行）：剔除窗口内最低 3 点后算 min/mean（远离单点噪声），阈值对 r3 标定：
#     红 <0.15（r3 的 0.2200 之下再留 32% 余量）；黄 <0.20。原值同时打印供对照。
_r200s = sorted(r200)
_r_rob = _r200s[3:] if len(_r200s) >= 10 else _r200s
_mean_rob = sum(_r_rob) / len(_r_rob) if _r_rob else 0
_ratio_rob = (min(_r_rob) / _mean_rob) if _mean_rob > 0 else 0
if _ratio_rob < 0.15:
    flags.append("RED:T1 剔3最低后 min/mean=%.3f <0.15（原始 %.3f，r3 基线 0.220）"
                 % (_ratio_rob, _ratio))
elif _ratio_rob < 0.20:
    flags.append("YEL:T1 剔3最低后 min/mean=%.3f <0.20（原始 %.3f，r3 基线 0.220）"
                 % (_ratio_rob, _ratio))
elif n_lt10_all > 0:
    notes.append("T1 原始 min/mean=%.3f（剔3最低 %.3f）lt10=%d 条，均未越线"
                 % (_ratio, _ratio_rob, n_lt10_all))
else:
    notes.append("实测 min/mean 原始 %.3f / 剔3最低 %.3f（r3 基线 0.220）"
                 % (_ratio, _ratio_rob))
# T1b 单窗多条击穿（比单点硬：要求 2 条 <0.105 或 1 条 <0.095）
#   2026-10-30 11:20 降级为旁证：绝对地板 0.105/0.095 是按**单遍曝光**标定的（r3 全程 min 0.1596）。
#   mix-v5 的 kitty 段是**第 2 遍**曝光（r3 已训 1 遍 + 本轮 1 遍），argmin 地板必然更低 —— 实测 min 0.0723。
#   这是 rehearsal 的算术后果，靠绝对阈值判会把后半程全程报红（报警疲劳）。
#   真正的风险（RE 是否被磨坏）由训后多 checkpoint 评测回答：post_train_mix_v5.sh 选优。
_c105 = sum(1 for x in r200 if x < 0.105)
_c095 = sum(1 for x in r200 if x < 0.095)
if _c105 >= 2 or _c095 >= 1:
    notes.append("T1b 单窗 loss<0.105=%d / <0.095=%d（绝对地板，按单遍标定；第2遍曝光下必然触发）"
                 % (_c105, _c095))
# T1c 绝对兜底（0.09 ≈ mean 0.23 的 0.39 倍，与比值判据在此汇合）—— 同上降级
if _min_now < 0.090:
    notes.append("T1c min %.4f <0.090（绝对兜底，按单遍标定；第2遍曝光下最低点必然更低）" % _min_now)
# T2 单窗 200 步 ltrel >= 6 条
#   2026-10-30 降级为【旁证】：thr_rel 是按当前 mean−1.74σ 换算的移动阈值，
#   p50 下移时阈值跟着下移，健康学习阶段也会筛出更多"简单样本" —— 与固定阈值假报警同族。
#   实测（mix-v5 step 878）：ltrel 3.6%→5.5% 跳档，同时 lt15=0 / lt10=0 / min 稳定 / gap 收窄，
#   四条硬指标全清白 ⇒ 不能凭它判红。真记忆化判据见 T6（分位缺口）。
if ltrel_200 >= 6:
    notes.append("T2 单窗200步 ltrel=%d(绝对%d) 条，相对口径旁证" % (ltrel_200, lt15_200))
# T3 累计 ltrel 异常（2026-10-29 19:35 修正阈值口径）
#   原写法 `step>=2500 and n_rel_all > 15` 是【设计缺陷】：
#     历史率 8/568 = 1.41%，总记录数 = 7414步/5 = 1483 条
#     ⇒ 按历史率外推的终值是 20.9 条，而阈值定 15 ⇒ 正常训练必然触发。
#   改为【率判据 + 绝对兜底】：
#     率超历史 1.8 倍（1.41% → 2.54%）且绝对数 > 25 才判 RED。
_HIS_RATE = float(os.environ.get("HIST_RATE", "%r" % (8.0 / 568.0)))
_cur_rate = n_rel_all / float(len(rows) + BASE_N)
_cur_pct = 100.0 * _cur_rate
_his_pct = 100.0 * _HIS_RATE
if step >= 2500 and _cur_rate > _HIS_RATE * 1.8 and n_rel_all > 25:
    notes.append("T3 累计 ltrel 率 %.2f%% > 历史 %.2f%%x1.8 (n=%d)，相对口径旁证"
                 % (_cur_pct, _his_pct, n_rel_all))
# 率超历史 1.4 倍即黄（1.41% → 1.97%），比绝对阈值更早、更稳
elif step >= 2500 and _cur_rate > _HIS_RATE * 1.4 and n_rel_all > 12:
    notes.append("T3 累计 ltrel 率 %.2f%% > 历史 %.2f%%x1.4 (n=%d)，相对口径旁证"
                 % (_cur_pct, _his_pct, n_rel_all))
# T4 min < 0.09 连续 2 窗（离开 0.15 擦边区，转真下钻）
if min_cur < 0.09 and prev.get("min", 9) < 0.09:
    notes.append("T4 min 连续 2 窗 <0.09（当前 %.4f）—— 绝对地板，按单遍标定，第2遍曝光必然触发" % min_cur)
# T5 【2026-10-29 19:44 重写】原 min 单点判据被极值统计证伪，已废弃
#   原写法：min 三次下钻 0.1132→0.1098→0.1043 当作系统性趋势。
#   证伪：min 是样本量 N 的极值统计量，分布不变时也会随 N 增大而下移：
#         E[min] ≈ μ − σ·√(2 ln N)，σ≈0.06，N 568→1328 ⇒ 期望下移 0.23σ = 0.014
#         纯抽样期望 min ≈ 0.1132 − 0.014 = 0.0992，而实测 0.1043 **还高于它**
#         ⇒ 这 7.9% 的下移比「什么都没发生只是多看了 760 条样本」还小。
#   窗级也不单调：2700 窗 0.1317 → 3000 窗 0.1098 → 3300 窗 0.1180（反弹）→ 3600 窗 0.1043
#   p5 分位 0.1431/0.1582/0.2024/0.1577 全程平走甚至上行 —— 左尾的「体」没动，只有「尖」在跳。
#   改用【绝对带 + 多条命中】：0.11 是不随 mean/σ 漂移的绝对量，且要求多条而非单点。
n_band_200 = sum(1 for x in r200 if x < 0.11)
if n_band_200 >= 3:
    notes.append("T5 单窗200步 loss<0.11 出现 %d 条（绝对带，按单遍标定 ⇒ 第2遍曝光必然触发）" % n_band_200)
# T5b 绝对地板（保留：同时要求「够低」和「连续」，能过滤单点极值噪声）
if _min_now < 0.095 and prev.get("min", 9) < 0.095:
    notes.append("T5b min 连续 2 窗 <0.095（当前 %.4f，绝对地板，同 T5 理由降为旁证）" % _min_now)

# ── T6 分位缺口（2026-10-30 新增；30 分钟后按实测校准为"非重叠块 + 加宽阈值"）────
# 记忆化签名：个别样本 loss 远低于分布主体 ⇒ p5 塌得比 p50 快、缺口【张开】。
# 整体下移（在学）⇒ 分位同时下移、缺口【收窄或持平】。
#
# ★ 2026-10-30 09:30 实测修正（monitor 提出，我用 verify_mixv5_gap_blocks.py 独立确认）：
#   ① 用【滑动窗】算 gap（每次挪 1 个点、相邻窗共享 39/40 样本）会把噪声平滑成假单调。
#      实测非重叠块是 `0.204 → 0.169 → 0.273 → 0.178 → 0.241 → 0.169 → 0.139`，
#      来回摆，极差 0.1334、sd 0.0430 ⇒ 抖动带 ±0.067 = 黄线 0.28 的 24%。
#      ⇒ 判据必须用【非重叠块】（本脚本改为按 step 200 对齐取块），且阈值必须 > 抖动带。
#   ② min/mean 不能用全量：全量 0.434 被 step 1005 一个孤立点（loss 0.2292）永久压住，
#      而近 200 步是 0.633。⇒ 用【本块内】的 min/mean。
#   校准后阈值：gap>0.38 红；gap>0.33 且块内 min/mean<0.50 黄。
def _q(v, p):
    v = sorted(v)
    n = len(v)
    if n < 2:
        return v[0] if v else 0.0
    k = (n - 1) * p
    lo = int(k)
    hi = min(lo + 1, n - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


_blk_start = ((rows[-1]["step"] - 1) // 200) * 200 + 1
_blk = [r["loss"] for r in rows if r["step"] >= _blk_start]
if len(_blk) < 20:
    notes.append("块%s 未满(n=%d)，gap 不打（块未跑满前值会漂，2026-10-30 实测：同块 n=27→31→38 时 0.1392→0.1391→0.1301）"
                 % (_blk_start, len(_blk)))
    _gap5 = _gap10 = 0.0
    _blk_ratio = 1.0
else:
    _gap5 = _q(_blk, .5) - _q(_blk, .05)
    _gap10 = _q(_blk, .5) - _q(_blk, .10)
    _blk_min = min(_blk)
    _blk_mean = sum(_blk) / len(_blk)
    _blk_ratio = _blk_min / _blk_mean if _blk_mean > 0 else 0.0
if len(_blk) < 20:
    pass          # 块未满：上面已打「块未满」旁证，不再打退化值 0.0000
elif _gap5 > 0.38:
    flags.append("RED:T6 gap(p50-p5)=%.4f >0.38 块%s 左尾张开" % (_gap5, _blk_start))
elif _gap5 > 0.33:
    # 2026-10-30：不再把「块内 min/mean<0.50」当黄线——实测该值块间摆动 0.24-0.63
    # （单点驱动，r3 全程参数 0.220 也能被它判黑），改由 T1 的「剔3最低」口径承担。
    flags.append("YEL:T6 gap(p50-p5)=%.4f >0.33 块%s 左尾张开（抖动带 ±0.067，需连续块确认）"
                 % (_gap5, _blk_start))
else:
    notes.append("gap(p50-p5)=%.4f 块%s(n=%d) gap10=%.4f 块内min/mean=%.3f"
                 % (_gap5, _blk_start, len(_blk), _gap10, _blk_ratio))

# YEL 级：个别简单样本（旁证，不报警）
if 0 < n_rel_all <= 10 and not flags:
    notes.append("ltrel=%d 条（相对口径，<=10 个别简单样本）" % n_rel_all)
# 相对口径触底告警（monitor-2a 2026-10-29 18:14 提出）
#   thr_rel = mean − 1.51σ ≈ mean − 0.107；threshold 下限压死 0.10。
#   ⇒ mean 降到 ~0.207 时 thr 顶到地板，相对口径失去区分力。
#   届时改用三条不依赖阈值的判据：lt10==0 / min 是否被打破 / 分窗率是否单调上升。
if thr_rel <= 0.1005:
    notes.append("thr_rel 触底(mean=%.3f) 相对口径已失效（仅信息，不报警）" % _mean_all)
if gmean < 0.3:
    flags.append("YEL:grad_norm 均值 %.3f <0.3" % gmean)

cur_lt25 = 100 * lt25 / len(recent)
if False:   # 2026-10-30 18:10 demoted: lt25 是位置相关量（mean 降到 0.42 后 40% 样本天然 <0.25），不是不变量
    if prev.get("lt25", 0) > 15:
        flags.append("YEL:loss<0.25 %.0f%%→%.0f%% 连续 2 窗 >15%%" % (prev.get("lt25", 0), cur_lt25))
# reserved 阈值（2026-10-29 修正）
#   VRAM_FRAC=0.93 × 11.91 GiB = 11.08 GiB 是 PyTorch 允许的上限。
#   reserved 到 11.03 仍 < 11.08，属「在允许量内的高水位碎片」，不是超限。
#   真正的危险信号是 OOM 或「99% util 但 power <60W」（换页），单看 reserved 会误报。
# reserved 阈值（2026-10-29 19:44 提前 RED）
#   VRAM_FRAC=0.93 × 11.91 GiB = 11.08 GiB 是 PyTorch 允许的上限。
#   崩溃后 free 已归 0，reserved 90 分钟从 10.498 涨到 10.707（+0.21），
#   按此速度约 3 小时触线 —— 崩过一次的机器不能等 11.10 才报。
#   RED 提前到 11.05（留 0.03 缓冲），YEL 仍 10.90。
if resv > 11.05:
    flags.append("RED:reserved %.2f GiB >11.05（距 VRAM_FRAC 上限 11.08 仅 %.2f）"
                 % (resv, 11.08 - resv))
elif resv > 10.90:
    flags.append("YEL:reserved %.2f GiB >10.90（碎片高水位，距上限 %.2f）" % (resv, 11.08 - resv))
if gpu_util not in ("?", "N/A") and int(float(gpu_util)) >= 99 and gpu_pw not in ("?", "N/A") and float(gpu_pw) < 60:
    flags.append("RED:99%% util 但 %.0fW（换页前兆）" % float(gpu_pw))
# 温度（2026-10-29 23:15 分档，原单档 >85 太晚）
#   实测后段稳定在 81–82℃ 平台（1 秒采样 10 秒，8/10 个点在 80.5–82.3），
#   而 watch 单点采样只记到 73–74℃ —— 漏检。多点采样后按此分档：
#   >84℃ 距 Tjmax 87 只剩 3℃，判 RED；>80℃ 判 YEL 提示平台抬高。
_t = float(gpu_t) if gpu_t not in ("?", "N/A") else 0
if _t > 84:
    flags.append("RED:温度 %.1f℃ >84（距 Tjmax 87 仅 3℃）" % _t)
elif _t > 80:
    flags.append("YEL:温度 %.1f℃ >80（持续平台，非尖峰）" % _t)

tag = "[ALERT] " + " | ".join(flags) if flags else "OK"
if notes:
    tag += " {旁证: " + " | ".join(notes) + "}"
print("[%s] step=%-5d %s loss=%.4f(近100 %.4f±%.3f) grad=%.3f "
      "min=%.4f ratio=%.3f cv=%.3f lt25=%.0f%% lt15=%d/%d ltrel=%d/%d(thr=%.3f) lt10=%d/%d "
      "mem=%s/%s GiB gpu=%s%% %sW %s℃ ckpt=%s"
      % (time.strftime("%m-%d %H:%M:%S"), step, tag, loss, mean_r, std_r, gmean,
         min_all, _ratio, _cv, 100 * lt25 / len(recent), n_lt15_all, len(rows) + BASE_N,
         n_rel_all, len(rows) + BASE_N, thr_rel, n_lt10_all, len(rows) + BASE_N,
         alloc, resv, gpu_util, gpu_pw, gpu_t,
         ",".join(str(c) for c in cks[-4:])))
PYEOF

  # 终止条件 2：训练进程没了（3 分钟内无新日志）→ 再确认一次后退出
  sleep 600
done

echo "[$(date '+%m-%d %H:%M:%S')] watcher 结束" >> "$LOG"
