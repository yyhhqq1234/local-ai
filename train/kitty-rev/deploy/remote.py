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

# Windows 控制台默认 GBK；远端回包一旦出现 ✓/⚠/中文，sys.stdout.write 会
# UnicodeEncodeError 直接崩（2026-10-21 踩过）。强制 UTF-8 + replace。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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



# ── MSYS2 路径转换归一化 ────────────────────────────────────────────────
# git-bash 会把看起来像 POSIX 绝对路径的参数转成 C:/Program Files/Git/root/...，
# 于是 sftp.put 拿到的远端路径是个 Windows 路径 → stat ENOENT（2026-10-22 又踩一次）。
# 这里就地纠正，并在发生时打印一行，别再依赖调用者记得 export MSYS2_ARG_CONV_EXCL。
_MSYS_PREFIXES = (
    r"C:/Program Files/Git", r"C:/Program Files (x86)/Git",
    r"C:/Users", r"C:/Windows",
)


def _fix_remote(p):
    """git-bash/MSYS2 会把 /root/... 转成 C:/Program Files/Git/root/... 或 C:/Users/.../root/...。
    本函数把任意被转换过的远端路径还原成 POSIX 绝对路径；还原不了就报错而不是照抄。
    2026-10-22 踩了第三次，所以在代码里兜住，不靠调用者记得 export MSYS2_ARG_CONV_EXCL。
    """
    q = p.replace("\\", "/")
    if q.startswith("/"):
        return q
    for token in ("/root/", "/home/", "/tmp/", "/opt/", "/data/"):
        i = q.find(token)
        if i >= 0:
            fixed = q[i:]
            print(f"[warn] 远端路径被 MSYS2 转换过，已还原：{p} → {fixed}")
            return fixed
    raise SystemExit(f"[FATAL] 远端路径不是 POSIX 绝对路径，且无法还原：{p}"
                     f"（调用方可能没设 MSYS2_ARG_CONV_EXCL='*'）")


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
        a.put[1] = _fix_remote(a.put[1])
        sftp.put(a.put[0], a.put[1], confirm=True)
        st = sftp.stat(a.put[1])
        print(f"[put] {a.put[0]} → {a.put[1]}  {st.st_size/2**20:.1f} MiB")
        sftp.close(); c.close(); return 0
    if a.get:
        # 断点续传：按本地已有字节数 seek，中断后重跑即从断点继续
        # （23.4 GiB 的回传包单次 sftp.get 中断就得从头再来，2026-10-21 改造）
        a.get[0] = _fix_remote(a.get[0])
        remote, local = a.get
        sftp = c.open_sftp()
        st = sftp.stat(remote)
        total = st.st_size
        offset = os.path.getsize(local) if os.path.isfile(local) else 0
        if offset > total:
            print(f"[get] 本地已有 {offset} B > 远端 {total} B，判定为不同文件，从头下载")
            offset = 0
        if offset == total and total > 0:
            print(f"[get] 已完成，跳过：{local}（{total/2**30:.2f} GiB）")
            sftp.close(); c.close(); return 0
        if offset:
            print(f"[get] 续传：本地已有 {offset/2**20:.1f} MiB / {total/2**20:.1f} MiB")
        else:
            print(f"[get] 开始：{total/2**20:.1f} MiB")
        chunk = 4 << 20
        done = offset
        t0 = time.time()
        last = t0
        mode = "ab" if offset else "wb"
        with sftp.open(remote, "rb") as rf, open(local, mode) as lf:
            rf.seek(offset)
            while True:
                data = rf.read(chunk)
                if not data:
                    break
                lf.write(data)
                done += len(data)
                now = time.time()
                if now - last >= 5 or done == total:
                    spd = (done - offset) / max(now - t0, 1e-6) / 2**20
                    pct = done / total * 100 if total else 100
                    eta = (total - done) / max((done - offset) / max(now - t0, 1e-6), 1) if done > offset else 0
                    print(f"  {pct:5.1f}%  {done/2**20:8.1f}/{total/2**20:.1f} MiB  "
                          f"{spd:6.2f} MiB/s  ETA {eta/60:.1f} min", flush=True)
                    last = now
        got = os.path.getsize(local)
        if got != total:
            print(f"[FATAL] 大小不符：本地 {got} / 远端 {total}，重跑本命令会从 {got} 续传")
            sftp.close(); c.close(); return 1
        print(f"[get] 完成 {remote} → {local}  {total/2**20:.1f} MiB  "
              f"耗时 {(time.time()-t0)/60:.1f} min")
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
