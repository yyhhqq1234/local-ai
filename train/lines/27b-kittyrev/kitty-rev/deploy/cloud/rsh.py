#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rsh.py —— 参数化 SSH 执行器（paramiko），AutoDL 实例每次重开 host/port/pass 都会变。

用法
  python rsh.py probe                       # 探活 + 打 GPU/磁盘/关键目录
  python rsh.py run "<cmd>"                 # 执行一条命令
  python rsh.py put <local> <remote>        # 上传
  python rsh.py get <remote> <local>        # 下载
  python rsh.py bg "<cmd>" <logpath>        # nohup 后台起

连接参数解析顺序（先命中先用）
  1) 命令行 --host/--port/--pass
  2) 环境 AUTODL_HOST / AUTODL_PORT / AUTODL_PASS
  3) 同目录 .autodl_host / .autodl_port / .autodl_pass
  4) 兜底 connect.bjb1.seetacloud.com : 45062 : 230svrtJiH9G
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

DEF_HOST = "connect.bjb1.seetacloud.com"
DEF_PORT = "45062"
DEF_PASS = "230svrtJiH9G"


def _f(name, default):
    p = os.path.join(HERE, name)
    if os.path.exists(p):
        v = open(p, encoding="utf-8").read().strip()
        if v:
            return v
    return default


def conn_info():
    host = _f(".autodl_host", DEF_HOST)
    port = int(_f(".autodl_port", DEF_PORT))
    pw = _f(".autodl_pass", DEF_PASS)
    return host, port, pw


def connect(timeout=60):
    import paramiko
    host, port, pw = conn_info()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username="root", password=pw, timeout=timeout,
              banner_timeout=timeout, auth_timeout=timeout,
              look_for_keys=False, allow_agent=False)
    tr = c.get_transport()
    if tr:
        tr.set_keepalive(30)
    return c


def run(cmd, timeout=600, echo=True):
    c = connect()
    try:
        _in, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        rc = out.channel.recv_exit_status()
        if echo:
            if o:
                sys.stdout.write(o)
            if e:
                sys.stderr.write(e)
        return rc, o, e
    finally:
        c.close()


def probe():
    cmds = [
        ("host", "hostname; date -Is"),
        ("gpu", "nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader"),
        ("disk", "df -h /root /root/autodl-tmp 2>/dev/null | tail -3"),
        ("dirs", "ls /root/autodl-tmp 2>/dev/null | head -20"),
        ("procs", "ps -eo pid,etime,cmd | grep -E '[t]rain_|[c]hain_|[l]lama-' | head -8"),
        ("py", "which python; python -c 'import torch;print(torch.__version__, torch.cuda.is_available())' 2>&1 | tail -1"),
    ]
    for k, cmd in cmds:
        print(f"===== {k} =====")
        try:
            run(cmd, timeout=120)
        except Exception as ex:
            print(f"[ERR] {type(ex).__name__}: {ex}")
        print()


def put(local, remote):
    import paramiko
    c = connect()
    try:
        sftp = c.open_sftp()
        t0 = time.time()
        sftp.put(local, remote)
        sz = sftp.stat(remote).st_size
        print(f"[OK] {local} -> {remote}  {sz} B  {time.time()-t0:.1f}s")
        sftp.close()
    finally:
        c.close()


def get(remote, local):
    c = connect()
    try:
        sftp = c.open_sftp()
        t0 = time.time()
        sftp.get(remote, local)
        print(f"[OK] {remote} -> {local}  {os.path.getsize(local)} B  {time.time()-t0:.1f}s")
        sftp.close()
    finally:
        c.close()


def bg(cmd, logpath):
    full = f"cd /root/autodl-tmp && setsid nohup bash -lc {shellq(cmd)} > {logpath} 2>&1 < /dev/null & echo $!"
    rc, o, e = run(full, timeout=60)
    print(f"[bg] pid={o.strip()} log={logpath}")


def shellq(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    a = sys.argv[1]
    if a == "probe":
        probe()
    elif a == "run":
        rc, _, _ = run(sys.argv[2], timeout=int(sys.argv[3]) if len(sys.argv) > 3 else 600)
        return rc
    elif a == "put":
        put(sys.argv[2], sys.argv[3])
    elif a == "get":
        get(sys.argv[2], sys.argv[3])
    elif a == "bg":
        bg(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
