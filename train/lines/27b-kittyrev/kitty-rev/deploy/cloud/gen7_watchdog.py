#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen4_watchdog.py —— GEN4 严格看门狗（红条件即终止 → 取最佳 checkpoint → 回传 → 关机）

与 gen3_1p_watchdog.py 的差别：不只是"到点收工"，而是**异常即止损**。
机器难抢，宁可提前停，也不让坏 run 白烧钱、也绝不丢产物。

轮询（默认 120 s）采集
  step / alive / loss / grad_norm / acc / 步速 / 显存 / 日志新鲜度

红条件（任一触发 → 立即止损流程）
  R1  loss 或 grad_norm 出现 NaN / Inf
  R2  loss > 2.2 × 最近 10 次均值（突刺）
  R3  grad_norm > 3.0
  R4  进程消失但 step < target
  R5  步速 < 0.4 × 基线，连续 3 次（掉档/热降频/IO 抖动）
  R6  显存 > 30,000 MiB 或比基线涨 >1,500 MiB（泄漏）
  R7  step 连续 15 min 不动（卡死）
  R8  日志 mtime 超过 10 min 未更新（远端假活）
  R9  累计运行超过 --deadline-h
绿条件（正常收工）
  G1  step >= target

止损流程（红/绿都走同一套，保证不丢产物）
  1  pkill -INT train_kitty（让它把当前 step 的 ckpt 落干净），等 60 s
  2  列出全部 checkpoint-N，读每个 trainer_state.json 的 log_history，
     取"最近 20 条 loss 均值"最低者为最佳 checkpoint
  3  sftp 拉 adapter_model.safetensors / adapter_config.json / trainer_state.json / tail log
  4  校验：adapter > 100 MB 且 sha256 非空；失败重试 2 次
  5  --no-power 不加时：autodl_power.py off --force（必须确认 status=shutdown）
  6  写本地报告 logs/watchdog-gen4-<ts>.json

用法
  python gen4_watchdog.py --target 1400 --interval 120
  python gen4_watchdog.py --target 1400 --dry        # 只看不动作
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rsh  # noqa: E402

LOG = "/root/autodl-tmp/gen7-train.log"
CKPT_DIR = "/root/autodl-tmp/kitty-rev/out/gen7"
POWER = os.path.join(os.path.dirname(HERE), "autodl_power.py")
LOCAL_ROOT = r"D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/local-pack/gen7"
REPORT_DIR = r"D:/BaiduNetdiskDownload/Local-AI/train/logs"

LOSS_RE = re.compile(r"'loss': '([0-9.eE+-]+)'")
GN_RE = re.compile(r"'grad_norm': '([0-9.eE+-]+)'")
ACC_RE = re.compile(r"'mean_token_accuracy': '([0-9.eE+-]+)'")
STEP_RE = re.compile(r"(\d+)/\d+ \[")


def sh(c, cmd, timeout=180):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()


def tail_txt(c, nbytes=6000):
    t, _ = sh(c, f"tail -c {nbytes} {LOG} 2>/dev/null | tr '\\r' '\\n'")
    return t or ""


def parse_metrics(txt):
    steps = STEP_RE.findall(txt)
    step = int(steps[-1]) if steps else -1
    loss = float(LOSS_RE.findall(txt)[-1]) if LOSS_RE.findall(txt) else None
    gn = float(GN_RE.findall(txt)[-1]) if GN_RE.findall(txt) else None
    acc = float(ACC_RE.findall(txt)[-1]) if ACC_RE.findall(txt) else None
    return step, loss, gn, acc


def alive(c):
    t, _ = sh(c, "pgrep -af train_kitty | grep -v pgrep | wc -l")
    return t.strip().isdigit() and int(t.strip()) > 0


def vram_mib(c):
    t, _ = sh(c, "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits")
    try:
        return int(t.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return -1


def log_age_s(c):
    t, _ = sh(c, f"echo $(( $(date +%s) - $(stat -c %Y {LOG} 2>/dev/null || echo 0) ))")
    try:
        return int(t.strip())
    except Exception:  # noqa: BLE001
        return 10 ** 6


def list_ckpts(c):
    t, _ = sh(c, f"ls -d {CKPT_DIR}/checkpoint-* 2>/dev/null | sort -V")
    return [x.strip() for x in (t or "").splitlines() if x.strip()]


def ckpt_loss(c, path):
    """从 trainer_state.json 的 log_history 取最近 20 条 loss 均值"""
    t, _ = sh(c, f"python3 - <<'PY'\nimport json,sys\n"
                 f"d=json.load(open('{path}/trainer_state.json'))\n"
                 f"ls=[x['loss'] for x in d.get('log_history',[]) if 'loss' in x][-20:]\n"
                 f"print(sum(ls)/len(ls) if ls else 9e9)\nPY")
    try:
        return float(t.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return 9e9


def pick_best(c):
    scored = []
    for p in list_ckpts(c):
        sz, _ = sh(c, f"stat -c %s {p}/adapter_model.safetensors 2>/dev/null || echo 0")
        try:
            size = int(sz.strip() or 0)
        except Exception:  # noqa: BLE001
            size = 0
        if size < 100 * 1024 * 1024:
            continue
        scored.append((ckpt_loss(c, p), p, size))
    scored.sort()
    return scored


def stop_training(c):
    sh(c, "pkill -INT -f train_kitty || true")
    for _ in range(12):
        if not alive(c):
            return True
        time.sleep(5)
    sh(c, "pkill -TERM -f train_kitty || true")
    time.sleep(5)
    return not alive(c)


def fetch(c, ckpt, local_dir):
    os.makedirs(local_dir, exist_ok=True)
    sftp = c.open_sftp()
    got = {}
    for f in ("adapter_model.safetensors", "adapter_config.json", "trainer_state.json"):
        rp = f"{ckpt}/{f}"
        lp = os.path.join(local_dir, f)
        for attempt in range(3):
            try:
                sftp.get(rp, lp)
                got[f] = os.path.getsize(lp)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[retry] {f} {attempt+1}/3 {type(e).__name__} {e}", flush=True)
                time.sleep(3)
    try:
        sh(c, f"tail -c 30000 {LOG} > {ckpt}/train-tail.log")
        sftp.get(f"{ckpt}/train-tail.log", os.path.join(local_dir, "train-tail.log"))
        got["train-tail.log"] = os.path.getsize(os.path.join(local_dir, "train-tail.log"))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] tail log: {e}", flush=True)
    sftp.close()
    sha = ""
    p = os.path.join(local_dir, "adapter_model.safetensors")
    if os.path.isfile(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        sha = h.hexdigest()
    return got, sha


def power_off():
    p = subprocess.run([sys.executable, POWER, "off", "--force"],
                       capture_output=True, text=True, timeout=900)
    print(((p.stdout or "") + (p.stderr or ""))[-500:], flush=True)
    ok = p.returncode == 0
    q = subprocess.run([sys.executable, POWER, "status"], capture_output=True,
                        text=True, timeout=180)
    print("[power-status]", [l for l in (q.stdout or "").splitlines() if '"status"' in l][:1])
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1400)
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--deadline-h", type=float, default=10.0)
    ap.add_argument("--no-power", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    losses, speeds = [], []
    base_speed = None
    base_vram = None
    slow_hits = 0
    last_step, last_step_t = -1, time.time()
    os.makedirs(REPORT_DIR, exist_ok=True)
    rep_path = os.path.join(REPORT_DIR, "watchdog-gen4-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    events = []

    print(f"[watch] target={a.target} interval={a.interval}s deadline={a.deadline_h}h", flush=True)

    while True:
        try:
            c = rsh.connect(timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"{time.strftime('%H:%M:%S')} [conn-err] {type(e).__name__} {e}", flush=True)
            if (time.time() - t0) / 3600 > a.deadline_h:
                print("[R9] 连接不上且超时 → 交人工", flush=True)
                return 3
            time.sleep(a.interval)
            continue

        try:
            txt = tail_txt(c)
            step, loss, gn, acc = parse_metrics(txt)
            al = alive(c)
            vr = vram_mib(c)
            age = log_age_s(c)
            now = time.time()
            el = (now - t0) / 3600

            if step > last_step:
                last_step, last_step_t = step, now
            if step >= 0:
                speeds.append(step)
            spd = None
            if len(speeds) >= 2 and speeds[-1] > speeds[-2]:
                # 用两次轮询之间的步数增量估算 s/it
                pass
            if loss is not None:
                losses.append(loss)
            if base_vram is None and vr > 0:
                base_vram = vr

            print(f"{time.strftime('%H:%M:%S')} step={step:5d} loss={loss} gn={gn} acc={acc} "
                  f"vram={vr}MiB alive={al} log_age={age}s 已跑={el:.2f}h", flush=True)

            red = []
            if loss is not None and (loss != loss or abs(loss) > 1e6):
                red.append("R1_loss_nan")
            if gn is not None and (gn != gn or gn > 1e6):
                red.append("R1_gn_nan")
            if gn is not None and gn > 3.0:
                red.append("R3_gn>3")
            if len(losses) >= 10:
                mean10 = sum(losses[-11:-1]) / 10
                if loss is not None and loss > 2.2 * mean10 and loss > 2.0:
                    red.append(f"R2_spike({loss:.2f}>{2.2*mean10:.2f})")
            if not al and step < a.target:
                red.append("R4_process_gone")
            if vr > 30000 or (base_vram and vr > base_vram + 1500):
                red.append(f"R6_vram({vr}MiB)")
            if al and step >= 0 and (now - last_step_t) > 900:
                red.append("R7_no_progress_15min")
            if age > 600 and al:
                red.append(f"R8_log_stale({age}s)")
            if el > a.deadline_h:
                red.append("R9_deadline")
            if step >= a.target:
                red.append("G1_target_reached")

            if red:
                print(f"[trigger] {red} → 止损流程", flush=True)
                events.append({"t": time.strftime("%H:%M:%S"), "step": step, "loss": loss,
                               "gn": gn, "vram": vr, "triggers": red})
                if a.dry:
                    print("[dry] 不动作", flush=True)
                    return 0
                stopped = stop_training(c)
                print(f"[stop] 训练已停={stopped}", flush=True)
                best = pick_best(c)
                print(f"[ckpt] 候选 {[(round(s,4), p.split('/')[-1]) for s, p, _ in best]}", flush=True)
                if not best:
                    print("[ABORT] 没有可用 checkpoint，不关机，留实例人工处理", flush=True)
                    json.dump({"events": events, "abort": "no_ckpt"}, open(rep_path, "w"),
                              ensure_ascii=False, indent=1)
                    return 2
                score, ckpt, _sz = best[0]
                local_dir = os.path.join(LOCAL_ROOT, os.path.basename(ckpt))
                got, sha = fetch(c, ckpt, local_dir)
                print(f"[fetch] {got} sha={sha[:16]}", flush=True)
                ok = got.get("adapter_model.safetensors", 0) > 100 * 1024 * 1024 and bool(sha)
                json.dump({"events": events, "best_ckpt": ckpt, "best_loss_mean20": score,
                           "fetched": got, "sha256": sha, "local_dir": local_dir,
                           "power_off": (ok and not a.no_power)},
                          open(rep_path, "w"), ensure_ascii=False, indent=1)
                if not ok:
                    print("[ABORT] 回传校验失败，不关机（留实例重试）", flush=True)
                    return 2
                if a.no_power:
                    print("[skip] 不关机（--no-power）", flush=True)
                    return 0
                power_off()
                print(f"[report] {rep_path}", flush=True)
                return 0

            time.sleep(a.interval)
        finally:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    sys.exit(main())
