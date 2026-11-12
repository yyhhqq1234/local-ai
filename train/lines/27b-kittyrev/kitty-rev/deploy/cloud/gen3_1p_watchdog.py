#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen3_1p_watchdog.py —— P0′ 训练看门狗（余额受限版：到 600 步即收工）

背景：账户余额只剩 ¥16，5090 按量计费 ≈ ¥2.9-3.5/h。
      P0′ 原计划 1500 步 ≈ 9 h（¥26-31）跑不完，改为 **600 步**：
        · 与 P0 同步数 → 数据是唯一变量，对比干净
        · 570 步 × 21.7 s ≈ 3.44 h ≈ ¥10-12，留 ¥4-6 兜底
判据与动作（每 5 分钟一次）：
  1  step < 600 且在跑       → 只打印
  2  step >= 600 或进程消失   → 收工：等 ckpt-600 → 拉 adapter → 校验 → 关机
  3  已跑 > 4.0 h 仍未 600    → 强制收工（防余额归零被硬停，损坏 ckpt）
  4  拉取失败                → 不关机，报警（留给主 agent 重试），避免丢失产物
用法：python gen3_1p_watchdog.py [--target 600] [--interval 300] [--dry]
"""
import argparse
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rsh  # noqa: E402

LOG = "/root/autodl-tmp/gen3_1p-train3.log"
CKPT_DIR = "/root/autodl-tmp/kitty-rev/out/gen3_1p"
LOCAL_OUT = r"D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/local-pack/gen3_1p/adapter-600"
POWER = os.path.join(os.path.dirname(HERE), "autodl_power.py")  # HERE=.../deploy/cloud → .../deploy/autodl_power.py


def sh(c, cmd, timeout=180):
    _i, o, e = c.exec_command(cmd, timeout=timeout)
    return o.read().decode(errors="replace").strip(), e.read().decode(errors="replace").strip()


def last_step(c):
    txt, _ = sh(c, f"tail -c 3000 {LOG} 2>/dev/null | tr '\\r' '\\n' | grep -oE '[0-9]+/1500' | tail -1")
    m = re.match(r"(\d+)/", txt or "")
    return int(m.group(1)) if m else -1


def alive(c):
    txt, _ = sh(c, "pgrep -af train_kitty | grep -v pgrep | wc -l")
    return txt.strip().isdigit() and int(txt.strip()) > 0


def fetch(c):
    sftp = c.open_sftp()
    os.makedirs(LOCAL_OUT, exist_ok=True)
    got = []
    for f in ("adapter_model.safetensors", "adapter_config.json"):
        remote = f"{CKPT_DIR}/checkpoint-600/{f}"
        local = os.path.join(LOCAL_OUT, f)
        try:
            sftp.get(remote, local)
            got.append((f, os.path.getsize(local)))
        except Exception as e:
            print(f"[ERR] 拉取 {f}: {type(e).__name__} {e}", flush=True)
    # 顺带拉训练日志尾部
    try:
        sh(c, f"tail -c 20000 {LOG} > /tmp/tail.log && cp /tmp/tail.log {CKPT_DIR}/train-tail.log")
        sftp.get(f"{CKPT_DIR}/train-tail.log", os.path.join(LOCAL_OUT, "train-tail.log"))
        got.append(("train-tail.log", os.path.getsize(os.path.join(LOCAL_OUT, "train-tail.log"))))
    except Exception as e:
        print(f"[WARN] 日志拉取失败 {e}", flush=True)
    sftp.close()
    return got


def power_off():
    import subprocess
    p = subprocess.run([sys.executable, POWER, "off", "--force"],
                       capture_output=True, text=True, timeout=600)
    print((p.stdout or "")[-400:], (p.stderr or "")[-200:], flush=True)
    return p.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=600)
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--deadline-h", type=float, default=4.0)
    ap.add_argument("--dry", action="store_true", help="只打印不拉取不关机")
    a = ap.parse_args()

    t0 = time.time()
    print(f"[watch] target={a.target} 步  deadline={a.deadline_h}h  interval={a.interval}s", flush=True)
    while True:
        try:
            c = rsh.connect(timeout=60)
        except Exception as e:
            print(f"{time.strftime('%H:%M:%S')} [conn-err] {type(e).__name__} {e}", flush=True)
            time.sleep(a.interval)
            continue
        try:
            st, alive_ = last_step(c), alive(c)
            el = (time.time() - t0) / 3600
            print(f"{time.strftime('%H:%M:%S')}  step={st:4d}  alive={alive_}  已跑={el:.2f}h", flush=True)
            done = (st >= a.target) or (not alive_ and st > 0) or (el >= a.deadline_h)
            if not done:
                time.sleep(a.interval)
                continue
            print(f"[done-trigger] step={st} alive={alive_} 已跑={el:.2f}h → 收工流程", flush=True)
            if a.dry:
                print("[dry] 不拉取不关机", flush=True)
                return 0
            # 等 ckpt 落盘
            for i in range(30):
                txt, _ = sh(c, f"ls -la {CKPT_DIR}/checkpoint-600/adapter_model.safetensors 2>/dev/null | awk '{{print $5}}'")
                if txt.strip().isdigit() and int(txt.strip()) > 100 * 1024 * 1024:
                    print(f"[ckpt] checkpoint-600 就绪 {int(txt.strip())/1048576:.1f} MB", flush=True)
                    break
                print(f"[wait-ckpt] {i+1}/30 …", flush=True)
                time.sleep(20)
            got = fetch(c)
            print(f"[fetch] {got}", flush=True)
            ok = any(f == "adapter_model.safetensors" and sz > 100 * 1024 * 1024 for f, sz in got)
            if not ok:
                print("[ABORT] adapter 拉取失败，不关机（留实例供重试）；请人工处理", flush=True)
                return 2
            print("[power] 关机止损", flush=True)
            power_off()
            return 0
        finally:
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
