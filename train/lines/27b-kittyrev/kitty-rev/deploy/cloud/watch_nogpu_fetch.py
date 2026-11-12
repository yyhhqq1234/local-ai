#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""watch_nogpu_fetch.py —— 等实例变 running（含操作者在控制台做「无卡模式开机」）就自动补拉 ckpt 并关机

背景：AutoDL 的 power_on API 只认 GPU 分配（试过 gpu_num=0 / no_gpu / no_gpu_mode /
     power_type / gpu_index / cpu_only 六种参数，全部回「机器空闲GPU不足」），
     所以「无卡模式开机」只能由控制台发起。本脚本只做一件事：
       轮询 status → 一旦 running（不管怎么起来的）→ sftp 拉指定 ckpt → 关机
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpts", default="400,600")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--max-hours", type=float, default=6)
    ap.add_argument("--keep-power", action="store_true", help="拉完不关机")
    a = ap.parse_args()

    t0 = time.time()
    print(f"[watch] 等实例 running（无卡模式开机由控制台发起）· 最多 {a.max_hours}h", flush=True)
    while True:
        st = status()
        el = (time.time() - t0) / 3600
        print(f"{time.strftime('%H:%M:%S')} status={st} 已等={el:.2f}h", flush=True)
        if st == "running":
            break
        if el > a.max_hours:
            print("[give-up] 超时仍未 running")
            return 4
        time.sleep(a.interval)

    print("[ok] 实例已 running，开始拉取", flush=True)
    import paramiko
    host = open(os.path.join(CLOUD, ".autodl_host"), encoding="utf-8").read().strip()
    port = int(open(os.path.join(CLOUD, ".autodl_port"), encoding="utf-8").read().strip())
    pwd = open(os.path.join(CLOUD, ".autodl_pass"), encoding="utf-8").read().strip()
    t = paramiko.Transport((host, port))
    t.connect(username="root", password=pwd)
    s = paramiko.SFTPClient.from_transport(t)

    got = []
    for ck in [c.strip() for c in a.ckpts.split(",") if c.strip()]:
        name = f"checkpoint-{ck}"
        loc = os.path.join(LOCAL, name)
        os.makedirs(loc, exist_ok=True)
        for f in ("adapter_model.safetensors", "adapter_config.json", "trainer_state.json"):
            try:
                s.get(f"{REMOTE}/{name}/{f}", os.path.join(loc, f))
                sz = os.path.getsize(os.path.join(loc, f))
                print(f"[get] {name}/{f} {sz}", flush=True)
                if f == "adapter_model.safetensors" and sz > 100 * 1024 * 1024:
                    h = hashlib.sha256()
                    with open(os.path.join(loc, f), "rb") as fh:
                        for c in iter(lambda: fh.read(1 << 22), b""):
                            h.update(c)
                    got.append((name, sz, h.hexdigest()[:16]))
            except Exception as e:  # noqa: BLE001
                print(f"[ERR] {name}/{f} {type(e).__name__} {e}", flush=True)
        p = os.path.join(loc, "trainer_state.json")
        if os.path.isfile(p):
            d = json.load(open(p, encoding="utf-8"))
            ls = [x["loss"] for x in d.get("log_history", []) if "loss" in x]
            print(f"[loss] {name} n={len(ls)} last20_mean="
                  f"{(sum(ls[-20:])/max(1,len(ls[-20:]))):.4f}", flush=True)
    s.close()
    t.close()

    print("\n[fetched]", got, flush=True)
    if not a.keep_power:
        rc, out = run([PYP, "-X", "utf8", POWER, "off", "--force"], 900)
        print("[power-off]", ((out or "").strip().splitlines() or [""])[-1][:120], flush=True)
        print("[power-status]", status(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
