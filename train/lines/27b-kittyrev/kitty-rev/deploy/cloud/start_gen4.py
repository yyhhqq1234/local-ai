#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""start_gen4.py — GEN4 一键上线：开机 → 传数据 → 预检 → 开训（幂等，可重复跑）

前置：preflight_gen4.py 必须 13/13 PASS；本机 .venv 有 paramiko？没有则用 anaconda python 跑本脚本。

用法：
  C:/ProgramData/anaconda3/python.exe -X utf8 start_gen4.py            # 全流程
  C:/ProgramData/anaconda3/python.exe -X utf8 start_gen4.py --check    # 只看状态

它会做：
  1) 查实例状态；shutdown_cloning（克隆锁定）→ 直接报错退出，不重试
  2) power on 并等 SSH 就绪
  3) 用 paramiko 直传 gen4 数据（rsh.py put 在本机有 sftp FileNotFoundError，走 inline）
  4) 远端校验 sha256 前16位与本地一致，不一致即中止（不烧钱跑错数据）
  5) 跑 gen4_5090.sh pre（数据/INIT/显存三项自检，不训练）
  6) nohup 启训（STEPS=800 SAVE=200），打印 pid 与日志路径
  7) 本地拉起看门狗（后台作业），到 600 步自动拉 adapter + 关机
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time

W = r"D:\BaiduNetdiskDownload\Local-AI"
PYP = r"C:\ProgramData\anaconda3\python.exe"
POWER = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "autodl_power.py")
RSH = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "cloud", "rsh.py")
DATA = os.path.join(W, "train", "lines", "27b-kittyrev", "data", "versions", "gen4-nsfw-kitty.jsonl")
RDATA = "/root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen4-nsfw-kitty.jsonl"
INIT = "/root/autodl-tmp/kitty-rev/out/gen3_1p/checkpoint-600"
LOG = "/root/autodl-tmp/gen4-train.log"


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def status():
    rc, out = run([PYP, "-X", "utf8", POWER, "status"], 120)
    st = "unknown"
    for line in out.splitlines():
        if '"status"' in line:
            st = line.split('"status":')[1].strip().strip('",')
            break
    return st, out


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:16]


def upload():
    """inline paramiko 上传（rsh.py put 在本机不可用）"""
    import paramiko  # noqa: F401
    host = open(os.path.join(os.path.dirname(RSH), ".autodl_host"), encoding="utf-8").read().strip()
    port = int(open(os.path.join(os.path.dirname(RSH), ".autodl_port"), encoding="utf-8").read().strip())
    pwd = open(os.path.join(os.path.dirname(RSH), ".autodl_pass"), encoding="utf-8").read().strip()
    t = paramiko.Transport((host, port))
    t.connect(username="root", password=pwd)
    sftp = paramiko.SFTPClient.from_transport(t)
    try:
        sftp.stat(os.path.dirname(RDATA))
    except IOError:
        print("[err] 远端目录不存在，先确认实例已就绪")
        raise
    size = os.path.getsize(DATA)
    print(f"[put] {os.path.basename(DATA)} {size/1048576:.1f} MiB → {RDATA}", flush=True)
    sftp.put(DATA, RDATA, confirm=True)
    st = sftp.stat(RDATA)
    print(f"[put] 远端大小 {st.st_size} 字节", flush=True)
    sftp.close()
    t.close()
    return st.st_size == size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    st, out = status()
    print(f"[status] {st}")
    if a.check:
        print(out[:400])
        return 0
    if st != "shutdown":
        print(f"[stop] 实例状态 {st}，不是干净 shutdown；克隆锁定/运行中都不动它")
        return 2

    print("[power] 开机…", flush=True)
    rc, out = run([PYP, "-X", "utf8", POWER, "on", "--wait", "480"], 600)
    print(out.strip().splitlines()[-3:] if out.strip() else out)
    if rc != 0:
        print("[stop] 开机失败")
        return 3

    local_sha = sha16(DATA)
    print(f"[sha] 本地 {local_sha}")
    if not upload():
        print("[stop] 上传后大小不一致")
        return 4

    rc, out = run([PYP, "-X", "utf8", RSH, "run",
                   f"sha256sum {RDATA} | cut -c1-16"], 180)
    got = out.strip().splitlines()[-1].strip() if out.strip() else ""
    print(f"[sha] 远端 {got}")
    if got != local_sha:
        print("[stop] sha 不一致，拒绝开训")
        return 5

    print("[pre] 跑远端预检（不训练）…", flush=True)
    rc, out = run([PYP, "-X", "utf8", RSH, "run",
                   "cd /root/autodl-tmp/kitty-rev && bash kitty-rev/deploy/cloud/gen4_5090.sh pre"],
                  1800)
    tail = "\n".join(out.strip().splitlines()[-12:])
    print(tail)
    if "FATAL" in out or "Traceback" in out:
        print("[stop] 预检失败")
        return 6

    print("[train] 启训 800 步（SAVE=200）…", flush=True)
    cmd = (f"cd /root/autodl-tmp/kitty-rev && DATA={RDATA} INIT={INIT} "
           f"nohup bash kitty-rev/deploy/cloud/gen4_5090.sh train > {LOG} 2>&1 & echo pid=$!")
    rc, out = run([PYP, "-X", "utf8", RSH, "run", cmd], 180)
    print(out.strip()[-300:])
    print(f"[ok] 日志 {LOG}")
    print("\n下一步（本地后台）：")
    print(f'  {PYP} -X utf8 train/lines/27b-kittyrev/kitty-rev/deploy/cloud/gen3_1p_watchdog.py '
          f'--target 600 --interval 300 > train/logs/watchdog-gen4.log 2>&1')
    return 0


if __name__ == "__main__":
    sys.exit(main())
