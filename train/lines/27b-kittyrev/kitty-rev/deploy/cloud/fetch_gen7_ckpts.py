#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_gen7_ckpts.py —— 补拉 gen7 的 checkpoint-400/600（看门狗抓错了目录且选点失败）

背景（2026-11-02 20:20 实测）
  ① gen7_watchdog 的 LOCAL_ROOT 是从 gen4_watchdog 复制时没替换 → checkpoint-200 落进了 local-pack/gen4/
  ② ckpt_loss 仍返回 9e9（trainer_state 里 log_history 只有 40 条、键名正常，但远端 sftp 读取分支抛异常被吞）
     → "最佳 checkpoint" 退化成取第一个（checkpoint-200，只有 1/3 训练量）
  所以：先补拉 400/600，再在本地算 loss 均值挑最佳。

行为
  1) 若实例 shutdown → 循环尝试开机（每 120s，最多 --max-wait 分钟）
  2) sftp 拉 checkpoint-400 / checkpoint-600 的 adapter_model + adapter_config + trainer_state
  3) 本地算 last20_mean，打印排名
  4) 关机（--no-power 可跳过）
落位：local-pack/gen7/checkpoint-<N>/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

W = r"D:\BaiduNetdiskDownload\Local-AI"
PYP = r"C:\ProgramData\anaconda3\python.exe"
POWER = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "autodl_power.py")
CLOUD = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "cloud")
LOCAL = os.path.join(W, "train", "lines", "27b-kittyrev", "local-pack", "gen7")
REMOTE = "/root/autodl-tmp/kitty-rev/out/gen7"


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def status():
    rc, out = run([PYP, "-X", "utf8", POWER, "status"], 180)
    for line in out.splitlines():
        if '"status"' in line:
            return line.split('"status":')[1].strip().strip('",')
    return "unknown"


def ensure_running(max_minutes=20):
    t0 = time.time()
    while (time.time() - t0) / 60 < max_minutes:
        st = status()
        print(f"[status] {st}", flush=True)
        if st == "running":
            return True
        if st in ("shutdown", "unknown"):
            rc, out = run([PYP, "-X", "utf8", POWER, "on", "--wait", "420"], 700)
            if rc == 0:
                print("[power] 开机成功", flush=True)
                return True
            print("   on →", (out or "").strip().splitlines()[-1][:120], flush=True)
        time.sleep(120)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpts", default="400,600")
    ap.add_argument("--no-power", action="store_true")
    a = ap.parse_args()

    if not ensure_running():
        print("[FATAL] 没抢到 GPU，稍后再试")
        return 3

    import paramiko
    host = open(os.path.join(CLOUD, ".autodl_host"), encoding="utf-8").read().strip()
    port = int(open(os.path.join(CLOUD, ".autodl_port"), encoding="utf-8").read().strip())
    pwd = open(os.path.join(CLOUD, ".autodl_pass"), encoding="utf-8").read().strip()
    t = paramiko.Transport((host, port))
    t.connect(username="root", password=pwd)
    s = paramiko.SFTPClient.from_transport(t)

    scores = []
    for ck in [c.strip() for c in a.ckpts.split(",") if c.strip()]:
        name = f"checkpoint-{ck}"
        loc = os.path.join(LOCAL, name)
        os.makedirs(loc, exist_ok=True)
        ok = True
        for f in ("adapter_model.safetensors", "adapter_config.json", "trainer_state.json"):
            try:
                s.get(f"{REMOTE}/{name}/{f}", os.path.join(loc, f))
                print(f"[get] {name}/{f} {os.path.getsize(os.path.join(loc, f))}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[ERR] {name}/{f} {type(e).__name__} {e}", flush=True)
                ok = False
        p = os.path.join(loc, "trainer_state.json")
        if ok and os.path.isfile(p):
            d = json.load(open(p, encoding="utf-8"))
            ls = [x["loss"] for x in d.get("log_history", []) if "loss" in x]
            m20 = sum(ls[-20:]) / max(1, len(ls[-20:]))
            scores.append((m20, name, len(ls)))
            print(f"[loss] {name} n={len(ls)} last20_mean={m20:.4f}", flush=True)
        ap_file = os.path.join(loc, "adapter_model.safetensors")
        if os.path.isfile(ap_file):
            h = hashlib.sha256()
            with open(ap_file, "rb") as fh:
                for c in iter(lambda: fh.read(1 << 22), b""):
                    h.update(c)
            print(f"[sha] {name} {h.hexdigest()[:16]}", flush=True)
    s.close()
    t.close()

    if scores:
        scores.sort()
        print(f"\n[best] {scores[0][1]}  last20_mean={scores[0][0]:.4f}  (全部: "
              f"{[(round(x[0],4), x[1]) for x in scores]})")
    if not a.no_power:
        rc, out = run([PYP, "-X", "utf8", POWER, "off", "--force"], 900)
        print(((out or "").strip().splitlines() or [""])[-1][:120])
        print("[power-status]", status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
