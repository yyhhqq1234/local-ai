#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""retry_gen4.py —— 抢 GPU：反复尝试开机，成功后自动接 GEN4 全流程

背景（2026-11-02 实测）
  实例状态 shutdown（克隆锁已解除），但 autodl_power.py on 返回
  BadRequest: 机器空闲GPU不足  → 平台侧没有空闲 5090 可分配
  机器难抢，不能靠人盯。

行为
  · 每 --interval 秒查一次 status
  · status == shutdown → 试 on（含 --wait）；"GPU不足"/"克隆锁定" 都算软失败，继续等
  · 开机成功 → 立刻 exec start_gen7.py（传数据 → sha 校验 → 远端预检 → 开训 1400 步）
  · 开机成功且 start 返回 0 → 拉起 gen4_watchdog（严格看门狗，红条件即止损回传关机）
  · 达到 --max-hours 仍未抢到 → 退出码 4，日志里说明

用法
  python retry_gen4.py [--interval 150] [--max-hours 8] [--attempts 200]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

W = r"D:\BaiduNetdiskDownload\Local-AI"
PYP = r"C:\ProgramData\anaconda3\python.exe"
CLOUD = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "cloud")
POWER = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "autodl_power.py")
START = os.path.join(CLOUD, "start_gen7.py")
WATCH = os.path.join(CLOUD, "gen7_watchdog.py")
LOGDIR = os.path.join(W, "train", "logs")


def run(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def status():
    rc, out = run([PYP, "-X", "utf8", POWER, "status"], 180)
    for line in out.splitlines():
        if '"status"' in line:
            return line.split('"status":')[1].strip().strip('",')
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=150)
    ap.add_argument("--max-hours", type=float, default=8.0)
    ap.add_argument("--attempts", type=int, default=200)
    a = ap.parse_args()

    t0 = time.time()
    for i in range(1, a.attempts + 1):
        el = (time.time() - t0) / 3600
        if el > a.max_hours:
            print(f"[give-up] {el:.1f}h 内没抢到 GPU", flush=True)
            return 4
        st = status()
        print(f"{time.strftime('%H:%M:%S')} [{i}] status={st} 已等={el:.2f}h", flush=True)
        if st == "running":
            print("[resume] 实例已在运行，直接接 start_gen4", flush=True)
            rc, out = run([PYP, "-X", "utf8", START], 2400)
            print(out[-800:], flush=True)
            if rc != 0:
                print(f"[stop] start_gen4 返回 {rc}", flush=True)
                return rc
            break
        if st not in ("shutdown", "unknown"):
            time.sleep(a.interval)
            continue
        rc, out = run([PYP, "-X", "utf8", POWER, "on", "--wait", "420"], 600)
        tail = (out or "").strip().splitlines()[-2:]
        print("   on →", " | ".join(tail), flush=True)
        if rc == 0:
            print("[ok] 开机成功，接 start_gen4", flush=True)
            rc2, out2 = run([PYP, "-X", "utf8", START], 2400)
            print(out2[-1200:], flush=True)
            if rc2 != 0:
                print(f"[stop] start_gen4 返回 {rc2}（预检/上传失败，不启看门狗）", flush=True)
                return rc2
            break
        time.sleep(a.interval)
    else:
        print("[give-up] 尝试次数用尽", flush=True)
        return 4

    # 开训成功 → 拉起严格看门狗（后台作业，由调用方 job 管理）
    print("[watch] 拉起 gen7_watchdog（target=600, interval=120）", flush=True)
    log = os.path.join(LOGDIR, "watchdog-gen4.log")
    with open(log, "ab") as f:
        p = subprocess.Popen([PYP, "-X", "utf8", WATCH, "--target", "600", "--interval", "120"],
                             stdout=f, stderr=subprocess.STDOUT,
                             creationflags=0x00000008 | 0x00000200)
    print(f"[watch] pid={p.pid} log={log}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
