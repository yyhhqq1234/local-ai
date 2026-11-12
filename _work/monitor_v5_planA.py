#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
monitor_v5_planA.py — v5 门控 LoRA 续训（方案 A：10 段 × 400 步）监控器
================================================================================
零参数直接跑：
    train\\.venv\\Scripts\\python.exe _work\\monitor_v5_planA.py

行为：
  1) 自动定位「最新」的 train/lines/9b-oxcoder/out/v5-a*/ （按 mem-trace mtime 取最大）
  2) 读 train-log.jsonl（每 5 步）、mem-trace.jsonl（每步）、train/logs/v5-planA.log（编排）
  3) 打印单行紧凑摘要（供定时巡检贴用）
  4) 详细报告「追加」到 train/logs/monitor-YYYYMMDD.md（markdown 表格 + 异常清单）

铁律：
  · 只读。绝不修改训练配置、绝不写训练产物、绝不杀任何进程 / 不动任何信号。
  · 唯一写入 = train/logs/monitor-YYYYMMDD.md（本监控器自己的报告）
  · 输出 UTF-8；Windows 控制台自动切 utf-8

可选环境变量（都不传即为默认）：
  MON_WINDOW=20     步速采样窗口秒数（需要两帧 mem-trace 差分，默认 20s）
  MON_QUICK=1       跳过步速采样窗口（步速将回退为整段均值估算）
  MON_OUT=...       覆盖报告文件名（默认 monitor-YYYYMMDD.md）
  MON_ROWS=24970    数据集行数（epoch 校验用；默认读 train log 里的 "（24970 条）"）
  MON_GA=4          gradient_accumulation（epoch 校验用，默认从命令行参数解析）
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ─────────────────────────── 0. 基础设施 ───────────────────────────

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "train" / "lines" / "9b-oxcoder" / "out"
LOG_DIR = ROOT / "train" / "logs"
PLAN_LOG = LOG_DIR / "v5-planA.log"

GREEN, YELLOW, RED = "绿", "黄", "红"
RANK = {GREEN: 0, YELLOW: 1, RED: 2}

SEG_STEPS = 400          # 每段步数（判据里的 X/400）
FREE_GREEN, FREE_YELLOW = 0.9, 0.5
RESV_GREEN, RESV_YELLOW = 10.0, 10.6
SPEED_GREEN, SPEED_YELLOW = 7.0, 15.0
TEMP_GREEN, TEMP_YELLOW = 80.0, 87.0
GRAD_GREEN, GRAD_YELLOW = 10.0, 50.0
# 5 点 loss 均值的合理区间。bs=1 + ga=4 下逐点实测 1.22–2.53（新数据段），
# 均值通常落在 1.6–2.3。原 1.3–2.0 是尾段退火期的旧阈值，会在正常抖动段误报黄。
LOSS_LO, LOSS_HI = 1.20, 2.60
ADP_GREEN = (170.0, 180.0)      # MB
ADP_YELLOW = (100.0, 250.0)     # MB（超过 300 = 双层 LoRA → 红）
ADP_RED = 300.0


def read_jsonl(path, tail=None):
    """读 jsonl，容忍半行/空行。tail=None 读全部。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            rows = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows[-tail:] if tail else rows
    except Exception:
        return []


def read_text(path, limit_bytes=200_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit_bytes))
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def run_cmd(args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return (p.stdout or "").strip()
    except Exception:
        return ""


# ─────────────────────────── 1. 定位最新段 ───────────────────────────


def find_latest_segment():
    """在 out/v5-*/ 中按 mem-trace.jsonl / train-log.jsonl 的 mtime 取最新。
    跳过带 _INVALID_ 标记的目录（v1 数据游标缺陷产物）。"""
    cands = []
    for d in sorted(OUT_ROOT.glob("v5-*")):
        if not d.is_dir():
            continue
        if list(d.glob("_INVALID_*")):
            continue
        mt = d / "mem-trace.jsonl"
        tl = d / "train-log.jsonl"
        stamp = 0.0
        for p in (mt, tl):
            if p.exists():
                stamp = max(stamp, p.stat().st_mtime)
        if stamp:
            cands.append((stamp, d))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[-1][1]


def seg_number(seg_dir):
    """v5-b2 → 2；v5-a2 → 2；v5-s1 → 1。"""
    m = re.search(r"v5-[abs](\d+)", seg_dir.name)
    return int(m.group(1)) if m else 0


# ─────────────────────────── 2. 采集 ───────────────────────────


def gpu_snapshot():
    """nvidia-smi：温度 / 已用 / 总量 / 利用率。返回 dict 或 None。"""
    exe_cands = [
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Windows\Sysnative\nvidia-smi.exe",
        "nvidia-smi",
    ]
    flags = ["--query-gpu=memory.used,memory.total,memory.free,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"]
    for exe in exe_cands:
        out = run_cmd([exe] + flags)
        if not out:
            continue
        line = out.splitlines()[0]
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            return {
                "used_mib": float(parts[0]),
                "total_mib": float(parts[1]),
                "free_mib": float(parts[2]),
                "temp_c": float(parts[3]),
                "util_pct": float(parts[4]),
                "src": exe,
            }
        except Exception:
            continue
    return None


def python_processes():
    """枚举 python.exe 及其 cmdline。优先 psutil，回退 tasklist。"""
    procs = []
    try:
        import psutil  # noqa
        for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "ppid"]):
            try:
                nm = (p.info.get("name") or "").lower()
                if nm.startswith("python") or nm.startswith("pythonw"):
                    cmd = " ".join(p.info.get("cmdline") or [])
                    rss = (p.info.get("memory_info").rss if p.info.get("memory_info") else 0) or 0
                    procs.append({
                        "pid": p.info["pid"],
                        "ppid": p.info.get("ppid"),
                        "rss": rss,
                        "cmd": cmd,
                    })
            except Exception:
                continue
        return procs
    except Exception:
        pass

    out = run_cmd(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"])
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 5:
            try:
                pid = int(cols[1])
            except Exception:
                continue
            m = re.search(r"([\d,]+)", cols[4])
            rss = int(m.group(1).replace(",", "")) if m else 0
            procs.append({"pid": pid, "ppid": None, "rss": rss * 1024, "cmd": ""})
    return procs


def parse_train_header(text):
    """从段 stdout 头部解析 数据行数 / ga / bs / ctx / lr / out（字段顺序无关）。"""
    info = {}
    # ★ 行数优先取「剩余 N 条」（--skip-samples 之后本段真实可训条数）
    #   原正则 \(N 条\) 会先命中「（实跳 8000 条）」→ epoch 期望值分母用错 → 误报 epoch 错位
    m = re.search(r"剩余\s*(\d+)\s*条", text)
    if m:
        info["rows"] = int(m.group(1))
    for key, pat, cast in (
        ("ctx", r"ctx=(\d+)", int),
        ("ga", r"\bga=(\d+)", int),
        ("lr", r"\blr=([\d.eE+-]+)", str),
        ("epochs", r"\bep=([\d.]+)", str),
        ("out", r"out\s+=\s+(\S+)", str),
    ):
        m = re.search(pat, text)
        if m:
            try:
                info[key] = cast(m.group(1))
            except Exception:
                pass
    if "rows" not in info:
        m = re.search(r"\((\d+)\s*条\)", text)
        if m:
            info["rows"] = int(m.group(1))
    return info


def parse_plan_log(text, seg_no):
    """从编排日志抓段起点时间 / 段标签 / 冷却标记。"""
    info = {"seg_start": None, "seg_end": None, "seg_init": None, "cooling": False, "last_line": ""}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines:
        info["last_line"] = lines[-1]
    # 段启动行：---- 第 N 段：init=... · out=... ----
    for ln in lines:
        m = re.match(r"\[([\d-]+ [\d:]+)\]\s+---- 第 (\d+) 段：init=(\S+?)\s+·", ln)
        if m and int(m.group(2)) == seg_no:
            info["seg_start"] = m.group(1)
            info["seg_init"] = m.group(3)
    # 冷却 / 段结束
    for ln in lines[-40:]:
        if re.search(r"冷却|cool", ln, re.I):
            info["cooling"] = True
        if re.search(r"第 \d+ 段.*(结束|完成)|退出码|全部完成", ln):
            info["seg_end"] = ln[:19]
    return info


def measure_rate(mem_path, last_step, window):
    """两帧差分测步速。返回 (s_per_step, dstep, dt, mode)。"""
    p = Path(mem_path)
    if not p.exists():
        return None, 0, 0.0, "no-file"
    if window <= 0:
        return None, 0, 0.0, "skip"
    try:
        n1 = len(read_jsonl(p))
        t1 = p.stat().st_mtime
    except Exception:
        return None, 0, 0.0, "err"
    time.sleep(window)
    try:
        n2 = len(read_jsonl(p))
        t2 = p.stat().st_mtime
    except Exception:
        return None, 0, 0.0, "err"
    dstep, dt = n2 - n1, t2 - t1
    if dstep > 0 and dt > 0:
        return dt / dstep, dstep, dt, "diff"
    return None, dstep, dt, "stall"


def estimate_rate_from_plan(plan, last_step, load_sec=90):
    """采样窗口失败时的兜底：段启动墙钟 → 现在 ÷ 已训步数（扣掉模型加载 90s）。"""
    st = plan.get("seg_start")
    if not st or not last_step or last_step <= 20:
        return None
    try:
        t0 = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    elapsed = (datetime.now() - t0).total_seconds() - load_sec
    if elapsed <= 10:
        return None
    return max(0.5, elapsed / last_step)


# ─────────────────────────── 3. 判据 ───────────────────────────


def j_free(v):
    if v is None:
        return YELLOW, "无数据"
    if v <= 0:
        return RED, f"{v:.2f} GiB 已归零"
    if v >= FREE_GREEN:
        return GREEN, f"{v:.2f} ≥ {FREE_GREEN}"
    if v >= FREE_YELLOW:
        return YELLOW, f"{v:.2f} 在 {FREE_YELLOW}–{FREE_GREEN}"
    return RED, f"{v:.2f} < {FREE_YELLOW}"


def j_reserved(v):
    if v is None:
        return YELLOW, "无数据"
    if v <= RESV_GREEN:
        return GREEN, f"{v:.3f} ≤ {RESV_GREEN}"
    if v <= RESV_YELLOW:
        return YELLOW, f"{v:.3f} 在 {RESV_GREEN}–{RESV_YELLOW}"
    return RED, f"{v:.3f} > {RESV_YELLOW}"


def j_speed(v, warming=False):
    if warming:
        return GREEN, "模型加载期 / 步数不足，不判"
    if v is None:
        return YELLOW, "本帧未采到（冷却 / 停滞 / 已跳过）"
    if v <= SPEED_GREEN:
        return GREEN, f"{v:.2f} ≤ {SPEED_GREEN}"
    if v <= SPEED_YELLOW:
        return YELLOW, f"{v:.2f} 在 {SPEED_GREEN}–{SPEED_YELLOW}"
    return RED, f"{v:.2f} > {SPEED_YELLOW}"


def j_temp(v):
    if v is None:
        return YELLOW, "nvidia-smi 不可达"
    if v < TEMP_GREEN:
        return GREEN, f"{v:.1f} < {TEMP_GREEN}"
    if v <= TEMP_YELLOW:
        return YELLOW, f"{v:.1f} 在 {TEMP_GREEN}–{TEMP_YELLOW}"
    return RED, f"{v:.1f} > {TEMP_YELLOW}"


def j_loss(losses):
    """losses: [(step, loss)] 按时间序。

    bs=1 的逐点 loss 方差天然大（实测 1.35–2.30 抖动），所以主判据用
    「最近 5 个记录点（25 步）均值」，逐点只用来看突刺 / NaN / 单调升。
    """
    vals = [v for _, v in losses if v is not None]
    if not vals:
        return YELLOW, "无数据"
    # NaN / Inf
    for s, v in losses:
        if v is not None and (v != v or v in (float("inf"), float("-inf"))):
            return RED, f"step {s} 出现 NaN/Inf"
    # 持续单调上升（最近 ≥5 点严格增 且 总涨幅 >0.3）
    if len(vals) >= 5:
        tailv = vals[-5:]
        if all(tailv[i] < tailv[i + 1] for i in range(len(tailv) - 1)) and (tailv[-1] - tailv[0]) > 0.3:
            return RED, f"连续 5 点单调上升 {tailv[0]:.3f}→{tailv[-1]:.3f}"
    med = sorted(vals)[len(vals) // 2]
    mx = max(vals)
    # bs=1 逐点方差天然大（实测 1.20–2.43 抖动属正常），单点突刺要「比例 + 绝对差」双超才报黄
    if med > 0 and mx > 2.8 * med and (mx - med) > 0.9:
        return YELLOW, f"单点突刺 {mx:.3f} > 2.8×中位 {med:.3f} 且差 >0.9"
    recent = vals[-5:]
    mean5 = sum(recent) / len(recent)
    rng = f"5点均值 {mean5:.3f}（逐点 {min(recent):.2f}–{max(recent):.2f}，全段 {min(vals):.2f}–{max(vals):.2f}）"
    if LOSS_LO <= mean5 <= LOSS_HI:
        return GREEN, rng
    return YELLOW, rng + f" 均值越界 {LOSS_LO}–{LOSS_HI}"


def j_grad(norms):
    vals = [v for _, v in norms if v is not None]
    if not vals:
        return YELLOW, "无数据"
    for s, v in norms:
        if v is not None and (v != v or abs(v) == float("inf")):
            return RED, f"step {s} grad_norm NaN/Inf"
    if max(vals) > GRAD_YELLOW:
        return RED, f"最大 {max(vals):.3f} > {GRAD_YELLOW}"
    # 连续 3 点 == 0
    run = 0
    for v in vals:
        run = run + 1 if v == 0 else 0
        if run >= 3:
            return RED, "连续 ≥3 点 grad_norm = 0"
    if max(vals) > GRAD_GREEN:
        return YELLOW, f"最大 {max(vals):.3f} 在 {GRAD_GREEN}–{GRAD_YELLOW}"
    if min(vals) < 0.1:
        return YELLOW, f"最小 {min(vals):.3f} < 0.1"
    return GREEN, f"{min(vals):.2f}–{max(vals):.2f} 落在 0.1–{GRAD_GREEN}"


def j_adapter(path, kind):
    """kind: 'final' 段末产物 | 'snapshot' 段内 checkpoint | 'baseline' 起点基线（段未结束时的等效判据）"""
    if path is None or not Path(path).exists():
        return YELLOW, "段未结束，产物未生成", None
    size_mb = Path(path).stat().st_size / 1e6
    tag = {"final": "", "snapshot": "（段内 checkpoint，段末复核）",
           "baseline": "（起点基线 v5-s1/final，段末复核）"}.get(kind, "")
    if size_mb > ADP_RED:
        return RED, f"{size_mb:.1f} MB > {ADP_RED} → 疑似双层 LoRA，必须作废{tag}", size_mb
    if ADP_GREEN[0] <= size_mb <= ADP_GREEN[1]:
        return GREEN, f"{size_mb:.1f} MB 在 {ADP_GREEN[0]}–{ADP_GREEN[1]}{tag}", size_mb
    if ADP_YELLOW[0] <= size_mb <= ADP_YELLOW[1]:
        return YELLOW, f"{size_mb:.1f} MB 偏离 {ADP_GREEN[0]}–{ADP_GREEN[1]}{tag}", size_mb
    return RED, f"{size_mb:.1f} MB 不在 {ADP_YELLOW[0]}–{ADP_YELLOW[1]}{tag}", size_mb


# ─────────────────────────── 4. 主动找 bug ───────────────────────────


def extra_checks(seg_dir, tr_rows, mem_rows, plan, gpu, procs, header, seg_no, rate_mode, mtimes, rate=None):
    """返回 [(级别, 标题, 说明, 处置)]"""
    items = []
    now = time.time()

    # 4.1 日志新鲜度
    ages = {k: now - v for k, v in mtimes.items() if v}
    mem_age = ages.get("mem", 0)
    tl_age = ages.get("trainlog", 0)
    if mem_age > 300 and not plan["cooling"]:
        items.append((RED, "日志停滞",
                      f"mem-trace {mem_age:.0f}s 未更新且无冷却标记",
                      "确认进程是否卡死（S_TRAIN 是否仍推进）；必要时重启该段"))
    elif mem_age > 120 and not plan["cooling"]:
        items.append((YELLOW, "日志迟滞", f"mem-trace {mem_age:.0f}s 未更新", "下一轮复查；持续则排查"))

    # 4.2 epoch 推进（每段内 step*ga/rows）
    rows = header.get("rows")
    ga = header.get("ga", 4)
    if rows and tr_rows:
        s, ep = tr_rows[-1].get("step"), tr_rows[-1].get("epoch")
        if s and ep is not None:
            exp = s * ga / rows
            if abs(ep - exp) > max(0.0005, exp * 0.05):
                items.append((YELLOW, "epoch 错位",
                              f"step {s} epoch={ep:.6f} 期望 {exp:.6f}",
                              "检查数据是否被重新 shuffle / 行数是否与 header 一致"))
            # 每段 400 步 × ga 4 = 1600 样本，占 24970 的 6.4%
            if s >= SEG_STEPS and ep * rows / ga < SEG_STEPS - 1:
                items.append((YELLOW, "步数不足", f"段末 step={s} 未达 {SEG_STEPS}", "检查 max-steps"))

    # 4.3 loss 长期不动（重复样本 / 过早收敛 / 数据未推进）
    vals = [r.get("loss") for r in tr_rows if r.get("loss") is not None]
    if len(vals) >= 6 and len(set(round(v, 6) for v in vals[-6:])) == 1:
        items.append((RED, "loss 完全冻结",
                      f"最近 6 个记录点 loss 恒为 {vals[-1]:.6f}",
                      "疑似数据重复 / dataloader 卡在同一 batch；停段核查数据索引"))

    # 4.4 lr 调度
    if header.get("lr") and tr_rows:
        seg_lr = float(header["lr"])
        cur_lr = tr_rows[-1].get("learning_rate")
        if cur_lr and cur_lr > seg_lr * 1.02:
            items.append((RED, "lr 超段配置", f"当前 {cur_lr:.3e} > 段配置 {seg_lr:.3e}", "立即核查 scheduler"))

    # 4.5 checkpoint 存在性
    ckpts = sorted([p.name for p in seg_dir.glob("checkpoint-*") if p.is_dir()])
    if tr_rows and tr_rows[-1].get("step", 0) >= SEG_STEPS and not ckpts:
        items.append((RED, "checkpoint 缺失",
                      f"已到 step {tr_rows[-1]['step']} 但无 checkpoint-* 目录",
                      "段末 save 失败 → 检查磁盘空间与 save_steps"))

    # 4.6 第二个 python 抢显存
    #   注意：Windows 上 train/.venv/Scripts/python.exe 是 redirector shim（RSS 几 MB），
    #   它会以「完全相同的 cmdline」再拉起真解释器 → 双 PID 同 cmdline 且互为父子 = 正常。
    tg = [p for p in procs if "train_qlora9b" in (p.get("cmd") or "")]
    if tg:
        by_pid = {p["pid"]: p for p in tg}
        groups = {}
        for p in tg:
            groups.setdefault(p.get("cmd") or "", []).append(p)
        foreign_groups = []
        for cmd, members in groups.items():
            pids = {m["pid"] for m in members}
            # 组内互为父子链 → 同一逻辑进程
            linked = len(members) == 1 or all(
                (m.get("ppid") in pids) or any(x.get("ppid") == m["pid"] for x in members)
                for m in members
            )
            if linked:
                root = max(members, key=lambda m: m.get("rss", 0))  # 真解释器（RSS 大）
                desc = f"PID {root['pid']}"
                if len(members) > 1:
                    others = [m["pid"] for m in members if m["pid"] != root["pid"]]
                    desc += f"（+venv redirector {', '.join(map(str, others))}）"
                items.append((GREEN, "训练进程", f"train_qlora9b 进程组：{desc} · RSS {root.get('rss',0)/2**30:.1f} GiB", "无"))
            else:
                foreign_groups.append(members)
        for members in foreign_groups:
            pids = ", ".join(str(m["pid"]) for m in members)
            items.append((RED, "多训练进程",
                           f"独立 train_qlora9b 进程 {len(members)} 个：{pids}",
                           "只应留 1 组；其余为残留 → 由操作者确认后处置（监控器不杀）"))
    big_other = [p for p in procs if "train_qlora9b" not in (p.get("cmd") or "") and p.get("rss", 0) > 800 * 2**20]
    if big_other:
        items.append((YELLOW, "旁路 python 进程",
                      "；".join(f"PID {p['pid']} RSS {p['rss']/2**30:.1f} GiB" for p in big_other),
                      "与本训练无关；确认是否占内存/显存，由操作者决定是否处置（监控器不杀）"))

    # 4.7 显存被外人占（nvidia-smi 已用 − torch reserved）
    if gpu and mem_rows:
        resv = mem_rows[-1].get("reserved_gib") or 0
        overhead = gpu["used_mib"] / 1024.0 - resv
        if overhead > 1.5:
            items.append((YELLOW, "显存外溢",
                          f"nvidia-smi 已用 {gpu['used_mib']/1024:.2f} GiB − torch reserved {resv:.2f} GiB = {overhead:.2f} GiB",
                          "有非本训练的显存占用（或 WDDM 共享）；核查旁路进程"))
        if gpu["total_mib"] and gpu["used_mib"] / gpu["total_mib"] > 0.92:
            items.append((YELLOW, "整卡占用偏高",
                          f"{gpu['used_mib']:.0f}/{gpu['total_mib']:.0f} MiB = {gpu['used_mib']/gpu['total_mib']*100:.1f}%",
                          "留神 WDDM 换页；如继续升则降 ctx 或降 VRAM_FRAC"))

    # 4.8 硬上限余量（VRAM_FRAC 0.88 → 10.51 GiB）
    if mem_rows:
        resv = mem_rows[-1].get("reserved_gib") or 0
        if resv > 10.2:
            items.append((RED, "逼近硬上限",
                          f"reserved {resv:.2f} GiB，硬上限 10.51 GiB（0.88×11.94）",
                          "脑裂风险：先停段，降 ctx 2048→1536 或 VRAM_FRAC 0.88→0.85 再续"))

    # 4.9 步速采样停滞
    if rate_mode == "stall" and not plan["cooling"]:
        items.append((YELLOW, "步速采样失败", "采样窗口内 mem-trace 未推进",
                      "若为段间冷却属正常；否则查是否卡在数据加载"))

    # 4.10 段速与 90min 硬上限（400 步 × 步速 > 5400s 则该段必被编排杀掉）
    if rate and rate * SEG_STEPS > 5400:
        items.append((YELLOW, "整段将超 90min 硬上限",
                      f"{rate:.2f}s/step × {SEG_STEPS} 步 = {rate*SEG_STEPS/60:.0f} min > 90 min",
                      "该段会被中途杀掉并留残缺 checkpoint；提前降 ctx 或改为 300 步/段"))

    # 4.11 ★结构性：段间数据游标不推进（v2 已修，检测到 skip_samples 即视为已修）
    #     train_qlora9b.py 的 --init-adapter 只搬 LoRA 权重，不搬 optimizer/scheduler/数据位置；
    #     每段都是全新 Trainer + 固定 --seed，随机采样序列完全一致 →
    #     每段只覆盖数据集最前面 (400×ga×bs) 条，多段 = 同一批样本重复 N 次。
    #     修法：train_qlora9b.py 新增 --skip-samples N，编排按 N = 起点 + i×400×ga 递增。
    init = (plan.get("seg_init") or "").replace("\\", "/")
    _seg_log_txt = read_text(LOG_DIR / f"{seg_dir.name}-train.log")
    _skip_fixed = "skip_samples=" in _seg_log_txt
    if seg_no >= 2 and init.endswith("/final") and header.get("rows") and not _skip_fixed:
        ga = header.get("ga", 4)
        per_seg = SEG_STEPS * ga  # bs=1
        rows = header["rows"]
        pct = per_seg / rows * 100
        items.append((RED, "段间数据游标不推进（未修）",
                      f"{seg_no} 段 init=`{init}`（--init-adapter）且日志无 skip_samples → 每段新 Trainer + "
                      f"固定 seed → 每段只训前 {per_seg} 条（{pct:.1f}% of {rows}），"
                      f"多段=同一批样本反复；epoch 每段从 0 重算即病征",
                      "立即停编排，确认 train_qlora9b.py 已加 --skip-samples 且编排传入递增 N"))
    elif _skip_fixed:
        # 已修：核验 skip 值推进是否与段号匹配
        _m = re.search(r"skip_samples=(\d+)", _seg_log_txt)
        if _m:
            _skip_val = int(_m.group(1))
            _expect = 6400 + (seg_no - 2) * SEG_STEPS * header.get("ga", 4)
            if _skip_val < 6400:
                items.append((RED, "skip_samples 未生效",
                              f"读到 skip_samples={_skip_val}，应 ≥6400", "停编排报主 agent"))
            elif abs(_skip_val - _expect) > SEG_STEPS * header.get("ga", 4):
                items.append((YELLOW, "skip_samples 与段号不匹配",
                              f"读到 {_skip_val}，按段号应为 {_expect}（差 >1600）",
                              "核对编排 SkipStart 与段号公式"))

    # 4.12 结构性：causal_conv1d 替身缺失 → 不能 packing（padding 浪费算力，步速偏慢）
    if "causal_conv1d" in read_text(LOG_DIR / f"{seg_dir.name}-train.log"):
        items.append(("结构", "causal_conv1d 回退",
                      "段日志首行：`causal_conv1d 替身缺失 → PyTorch 回退（慢，且不能 packing）` "
                      "→ 变长样本按 ctx=2048 补齐，有效 token 占比下降，步速与显存都被浪费",
                      "若可装 causal-conv1d 并支持 sm_120，则 `--packing` 能提速；"
                      "不装属已知取舍，只需知情，不是故障"))
    return items


# ─────────────────────────── 5. 主流程 ───────────────────────────


def main():
    window = float(os.environ.get("MON_WINDOW", "40"))
    if os.environ.get("MON_QUICK") == "1":
        window = 0

    seg_dir = find_latest_segment()
    if seg_dir is None:
        print("[MONITOR] 未找到任何 out/v5-a* 段目录，无法监控")
        return 2

    seg_no = seg_number(seg_dir)
    tr_rows = read_jsonl(seg_dir / "train-log.jsonl")
    mem_rows = read_jsonl(seg_dir / "mem-trace.jsonl", tail=400)
    seg_stdout = read_text(LOG_DIR / f"{seg_dir.name}-train.log")
    header = parse_train_header(seg_stdout)
    plan = parse_plan_log(read_text(PLAN_LOG), seg_no)

    mtimes = {}
    for key, p in (("mem", seg_dir / "mem-trace.jsonl"),
                   ("trainlog", seg_dir / "train-log.jsonl"),
                   ("plan", PLAN_LOG)):
        mtimes[key] = p.stat().st_mtime if p.exists() else None

    gpu = gpu_snapshot()
    procs = python_processes()

    # 步速
    last_step = mem_rows[-1].get("step") if mem_rows else 0
    rate, dstep, dt, rate_mode = measure_rate(seg_dir / "mem-trace.jsonl", last_step, window)
    # 兜底：两帧差分失败（窗口内未推进 / 冷却 / 文件不可读）→ 用段启动墙钟估整段均值
    if rate is None:
        _r2 = estimate_rate_from_plan(plan, last_step)
        if _r2:
            rate, rate_mode = _r2, "elapsed"

    # 指标
    last_mem = mem_rows[-1] if mem_rows else {}
    last_tr = tr_rows[-1] if tr_rows else {}
    losses = [(r.get("step"), r.get("loss")) for r in tr_rows]
    norms = [(r.get("step"), r.get("grad_norm")) for r in tr_rows]

    # adapter：段末 final 优先，其次段内 checkpoint，最后起点基线（段未结束时）
    adp_path, adp_kind = None, "baseline"
    if (seg_dir / "final" / "adapter_model.safetensors").exists():
        adp_path, adp_kind = seg_dir / "final" / "adapter_model.safetensors", "final"
    elif (seg_dir / "adapter_model.safetensors").exists():
        adp_path, adp_kind = seg_dir / "adapter_model.safetensors", "final"
    else:
        snaps = sorted(seg_dir.glob("checkpoint-*/adapter_model.safetensors"))
        if snaps:
            adp_path, adp_kind = snaps[-1], "snapshot"
        else:
            base = OUT_ROOT / "v5-s1" / "final" / "adapter_model.safetensors"
            if base.exists():
                adp_path, adp_kind = base, "baseline"

    # free 判据以 nvidia-smi 物理空闲为准：mem-trace 的 free_gib 是 Python 视角，
    # 已扣掉 torch reserved 缓存，恒定偏低 → 会把健康段误判成黄/红（实测 0.51 vs 物理 1.26）
    _free_phys = ((gpu["free_mib"] / 1024.0)
                  if (gpu and gpu.get("free_mib") is not None)
                  else last_mem.get("free_gib"))
    checks = [
        ("free_gib(物理)", ) + j_free(_free_phys),
        ("reserved_gib", ) + j_reserved(last_mem.get("reserved_gib")),
        ("步速 s/step", ) + j_speed(rate, warming=(last_step < 20)),
        ("loss 趋势", ) + j_loss(losses),
        ("grad_norm", ) + j_grad(norms),
        ("温度 °C", ) + j_temp(gpu["temp_c"] if gpu else None),
        ("adapter 体积", ) + j_adapter(adp_path, adp_kind),
    ]
    worst = max((c[1] for c in checks), key=lambda x: RANK[x])

    extras = extra_checks(seg_dir, tr_rows, mem_rows, plan, gpu, procs, header,
                          seg_no, rate_mode, mtimes, rate)
    red_extras = [e for e in extras if e[0] == RED]
    if red_extras:
        worst = RED

    # 一句话结论
    if worst == GREEN:
        concl = f"{seg_dir.name} 健康：显存余量充足，loss/grad 平稳，步速 {rate:.2f}s/step" if rate else f"{seg_dir.name} 健康"
    elif worst == YELLOW:
        ynames = [c[0] for c in checks if c[1] == YELLOW] + [e[1] for e in extras if e[0] == YELLOW]
        concl = "需关注：" + ("、".join(ynames) if ynames else "存在黄项")
    else:
        rnames = [c[0] for c in checks if c[1] == RED] + [e[1] for e in red_extras]
        concl = "★红项：" + "、".join(rnames)
    struct = [e[1] for e in extras if e[0] == "结构"]
    if struct:
        concl += " ｜ 结构：" + "、".join(struct)

    # ── 单行摘要 ──
    hhmm = datetime.now().strftime("%H:%M")
    speed_txt = f"{rate:.2f}" if rate else "NA"
    temp_txt = f"{gpu['temp_c']:.1f}" if gpu else "NA"
    loss_txt = last_tr.get("loss")
    loss_txt = f"{loss_txt:.4f}" if isinstance(loss_txt, (int, float)) else "NA"
    line = (
        f"[MONITOR {hhmm}] seg={seg_no} step={last_step}/{SEG_STEPS} "
        f"loss={loss_txt} "
        f"lr={last_tr.get('learning_rate', 0):.2e} "
        f"步速={speed_txt}s/step "
        f"alloc={last_mem.get('alloc_gib', 0):.2f} "
        f"reserved={last_mem.get('reserved_gib', 0):.2f} "
        f"peak={last_mem.get('peak_gib', 0):.2f} "
        f"free={_free_phys if _free_phys is not None else 0:.2f} GiB(物理) "
        f"温度={temp_txt}°C "
        f"判定={worst} | {concl}"
    )
    print(line)

    # ── 详细报告（追加） ──
    out_name = os.environ.get("MON_OUT") or f"monitor-{datetime.now():%Y%m%d}.md"
    report = LOG_DIR / out_name
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def yn(v):
        return "—" if v is None else f"{v:.3f}"

    md = []
    if not report.exists():
        md.append("# v5 方案A 训练监控报告\n")
        md.append("> 由 `_work/monitor_v5_planA.py` 自动追加。只读采集，判据内置于脚本。\n")
        md.append("| 项 | 绿 | 黄 | 红 |")
        md.append("|---|---|---|---|")
        md.append("| free_gib | ≥0.9 | 0.5–0.9 | <0.5 或 0 |")
        md.append("| reserved_gib | ≤10.0 | 10.0–10.6 | >10.6 |")
        md.append("| 步速 | ≤7 | 7–15 | >15 |")
        md.append("| loss | 1.3–2.0 平稳 | 单点 >2× | NaN/Inf/单调升 |")
        md.append("| grad_norm | 0.1–10 | 10–50 | >50 或连续=0 |")
        md.append("| 温度 | <80 | 80–87 | >87 |")
        md.append("| adapter | 170–180 MB | 100–170 / 180–250 | >300 MB |")
        md.append("")
        md.append("> 口径说明：loss 主判据用 **最近 5 个记录点（25 步）均值**落 1.3–2.0，"
                  "逐点只用于 NaN/Inf、>2× 中位突刺、连续单调升检测（bs=1 逐点方差 1.35–2.30 属正常抖动）；"
                  "步速由 mem-trace 两帧差分实测（默认 40s 窗口，误差约 ±1 步），冷却期/停滞显示 NA；"
                  "adapter 体积在段未结束时按起点基线或段内 checkpoint 评估，段末 final 生成后自动切换正式判据。\n")

    md.append(f"## {ts} · {seg_dir.name} · 判定 {worst}\n")
    md.append(f"```")
    md.append(line)
    md.append(f"```\n")
    md.append("| # | 判据 | 结论 | 依据 |")
    md.append("|---|---|---|---|")
    for i, (name, verdict, evidence, *_rest) in enumerate(checks, 1):
        md.append(f"| {i} | {name} | {verdict} | {evidence} |")
    md.append("")
    md.append(f"- 段目录：`{seg_dir.relative_to(ROOT).as_posix()}`")
    md.append(f"- 最近步：{last_step}/{SEG_STEPS} · 采样模式 {rate_mode} · 窗口 {window:.0f}s · Δstep={dstep}")
    if gpu:
        md.append(f"- GPU：{gpu['used_mib']:.0f}/{gpu['total_mib']:.0f} MiB · util {gpu['util_pct']:.0f}% · "
                  f"{gpu['temp_c']:.1f}°C · via `{gpu['src']}`")
    md.append(f"- 数据：{header.get('rows', '?')} 条 · ga={header.get('ga', '?')} · ctx={header.get('ctx', '?')} · "
              f"段 lr={header.get('lr', '?')}")
    md.append(f"- 编排日志末行：`{plan['last_line'][:140]}`")
    md.append("")

    md.append("### 异常 / 隐患\n")
    noisy = [e for e in extras if e[0] != GREEN]
    infos = [e for e in extras if e[0] == GREEN]
    if not noisy:
        md.append("- 无\n")
    else:
        for lvl, title, detail, action in noisy:
            md.append(f"- **[{lvl}] {title}** — {detail}")
            if action and action != "无":
                md.append(f"  - 处置：{action}")
        md.append("")
    if infos:
        md.append("### 环境确认\n")
        for lvl, title, detail, action in infos:
            md.append(f"- {title}：{detail}")
        md.append("")

    reds = [c for c in checks if c[1] == RED] + [(e[0], e[1], e[2], e[3]) for e in red_extras]
    structs = [e for e in extras if e[0] == "结构"]
    md.append("### 处置建议\n")
    if not reds and worst == GREEN and not structs:
        md.append("- 无需干预\n")
    for item in reds:
        md.append(f"- **{item[1]}**：{item[2]} → {item[3] if len(item) > 3 else '见判据表'}")
    for lvl, title, detail, action in structs:
        md.append(f"- **（结构性，不随巡检消退）{title}** → {action}")
    md.append("")

    try:
        with open(report, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    except Exception as e:
        print(f"[MONITOR] 报告写入失败：{e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
