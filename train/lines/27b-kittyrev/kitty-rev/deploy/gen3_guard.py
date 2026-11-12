#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen3_guard.py —— 本机侧守护：轮询远端状态 → 取产物 → 自动关机（止损）

行为
  每 --interval 秒读远端 /root/autodl-tmp/kitty-rev/gen3-status.txt
    PRE/GATE/SMOKE/TRAIN → 打一行进度（含最新 loss/step）
    DONE:<adapter_dir>   → 下载 adapter + 三段日志 → 校验大小 → 关机
    FAIL:<原因>          → 下载日志 → 关机（止损，不无限烧钱）
  关机走 autodl_power.py off --force（远端 poweroff 无效，PID1 受保护）

用法
  python gen3_guard.py                 # 常驻
  python gen3_guard.py --once          # 只查一次
  python gen3_guard.py --no-shutdown   # 只看不关
产物落 train/lines/9b-oxcoder/out/gen3-fetch/<ts>/
"""
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "cloud"))
import rsh  # noqa: E402

ROOT_R = "/root/autodl-tmp/kitty-rev"
STATUS_R = f"{ROOT_R}/gen3-status.txt"
LOG_R = f"{ROOT_R}/gen3-5090-full.log"
CHAIN_R = f"{ROOT_R}/gen3-chain.log"
TRAIN_LOCAL = os.path.dirname(os.path.dirname(HERE))  # train/
FETCH_BASE = os.path.join(TRAIN_LOCAL, "out", "gen3-fetch")

ADAPTER_FILES = ["adapter_model.safetensors", "adapter_config.json",
                 "README.md", "training_args.bin"]


def ts():
    return time.strftime("%Y%m%d-%H%M%S")


def read_status():
    try:
        rc, o, _ = rsh.run(f"cat {STATUS_R} 2>/dev/null", timeout=40, echo=False)
        return o.strip()
    except Exception as e:
        return f"<ssh-err:{type(e).__name__}>"


def tail_remote(path, n=3):
    try:
        rc, o, _ = rsh.run(f"tail -n {n} {path} 2>/dev/null", timeout=40, echo=False)
        return o.strip()
    except Exception:
        return ""


def fetch(adapter_dir):
    out = os.path.join(FETCH_BASE, ts())
    os.makedirs(out, exist_ok=True)
    print(f"[fetch] -> {out}")
    for f in ADAPTER_FILES:
        r = f"{adapter_dir}/{f}"
        l = os.path.join(out, f)
        try:
            rsh.get(r, l)
        except Exception as e:
            print(f"  [skip] {f}: {type(e).__name__}")
    for name, r in (("gen3-5090-full.log", LOG_R), ("gen3-chain.log", CHAIN_R)):
        try:
            rsh.get(r, os.path.join(out, name))
        except Exception as e:
            print(f"  [skip] {name}: {type(e).__name__}")
    return out


def verify(out):
    p = os.path.join(out, "adapter_model.safetensors")
    if not os.path.exists(p):
        return False, "缺 adapter_model.safetensors"
    sz = os.path.getsize(p)
    if sz < 100_000_000:
        return False, f"adapter 过小 {sz}"
    return True, f"{sz} B"


def shutdown(force=True):
    cmd = [sys.executable, os.path.join(HERE, "autodl_power.py"), "off"]
    if force:
        cmd.append("--force")
    print("[shutdown]", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip()[-500:])
    if r.returncode != 0:
        print("[shutdown][warn]", r.stderr.strip()[-300:])


def progress_line():
    st = read_status()
    if st.startswith("TRAIN") or st.startswith("SMOKE"):
        t = tail_remote(LOG_R, 2)
        m = re.findall(r"(\d+)/" + r"(\d+)", t)
        print(f"[guard {time.strftime('%H:%M')}] {st} | {t.replace(chr(10),' ')[:160]}", flush=True)
    else:
        print(f"[guard {time.strftime('%H:%M')}] {st}", flush=True)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-shutdown", action="store_true")
    a = ap.parse_args()

    while True:
        try:
            st = progress_line()
        except Exception as e:
            print(f"[guard] ssh err {type(e).__name__}: {e}", flush=True)
            st = ""

        if st.startswith("DONE:"):
            ad = st.split("DONE:", 1)[1].strip()
            out = fetch(ad)
            ok, why = verify(out)
            print(f"[verify] {'PASS' if ok else 'FAIL'} {why}")
            if ok and not a.no_shutdown:
                shutdown()
            return 0 if ok else 1
        if st.startswith("FAIL"):
            fetch("")
            if not a.no_shutdown:
                shutdown()
            return 2
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
