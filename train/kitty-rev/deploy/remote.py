#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""remote.py —— 用 paramiko 操作 AutoDL 实例（免交互密码）

用法:
  python remote.py --cmd "nvidia-smi; df -h /root/autodl-tmp"
  python remote.py --put <本地文件> <远端路径>
  python remote.py --get <远端文件> <本地路径>
  python remote.py --bg "bash cloud/run_autodl.sh smoke" --log /root/autodl-tmp/kitty-rev/smoke.log
  python remote.py --tail /root/autodl-tmp/kitty-rev/smoke.log -n 40

连接参数优先取环境变量：AUTODL_HOST / AUTODL_PORT / AUTODL_USER / AUTODL_PASS
"""
import argparse
import os
import sys
import time

import paramiko

HOST = os.environ.get("AUTODL_HOST", "connect.bjb1.seetacloud.com")
PORT = int(os.environ.get("AUTODL_PORT", "35299"))
USER = os.environ.get("AUTODL_USER", "root")
PASS = os.environ.get("AUTODL_PASS", "gpMW8alzDfoL")


def connect(timeout=20):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=timeout,
              banner_timeout=30, auth_timeout=30, look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd, timeout=600, quiet=False):
    chan = c.get_transport().open_session()
    chan.get_pty()
    chan.exec_command(cmd)
    out = []
    t0 = time.time()
    while True:
        if chan.recv_ready():
            out.append(chan.recv(65536).decode("utf-8", "replace"))
        if chan.exit_status_ready() and not chan.recv_ready():
            break
        if time.time() - t0 > timeout:
            out.append(f"\n[TIMEOUT after {timeout}s]\n")
            chan.close()
            break
        time.sleep(0.2)
    try:
        while chan.recv_ready():
            out.append(chan.recv(65536).decode("utf-8", "replace"))
    except Exception:
        pass
    text = "".join(out)
    if not quiet:
        sys.stdout.write(text)
        sys.stdout.flush()
    return chan.exit_status if chan.exit_status_ready() else -1, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", default="")
    ap.add_argument("--put", nargs=2, metavar=("LOCAL", "REMOTE"))
    ap.add_argument("--get", nargs=2, metavar=("REMOTE", "LOCAL"))
    ap.add_argument("--bg", default="")
    ap.add_argument("--log", default="")
    ap.add_argument("--tail", default="")
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    c = connect()
    if a.cmd:
        rc, _ = run(c, a.cmd, timeout=a.timeout)
        c.close()
        return 0 if rc == 0 else 1
    if a.put:
        sftp = c.open_sftp()
        sftp.put(a.put[0], a.put[1], confirm=True)
        st = sftp.stat(a.put[1])
        print(f"[put] {a.put[0]} → {a.put[1]}  {st.st_size/2**20:.1f} MiB")
        sftp.close(); c.close(); return 0
    if a.get:
        sftp = c.open_sftp()
        sftp.get(a.get[0], a.get[1])
        print(f"[get] {a.get[0]} → {a.get[1]}")
        sftp.close(); c.close(); return 0
    if a.bg:
        assert a.log, "--bg 需要 --log"
        cmd = f"cd /root/autodl-tmp/kitty-rev && nohup {a.bg} > {a.log} 2>&1 & echo BG_STARTED $!"
        rc, _ = run(c, cmd, timeout=30)
        c.close(); return 0
    if a.tail:
        rc, _ = run(c, f"tail -n {a.n} {a.tail}", timeout=30)
        c.close(); return 0
    ap.print_help()
    c.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
