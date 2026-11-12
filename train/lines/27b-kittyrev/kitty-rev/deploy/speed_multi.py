#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""speed_multi.py —— 测试 SSH/SFTP 多流并发能否叠加带宽

背景：单流实测 0.70 MiB/s，若多流能叠加，23 GiB 回传就能从 9 小时降到可接受范围。
用法：python speed_multi.py --remote /tmp/speedtest.bin --streams 4 --mb 200
"""
import argparse
import os
import threading
import time

import paramiko

HOST = os.environ.get("AUTODL_HOST", "connect.bjb1.seetacloud.com")
PORT = int(os.environ.get("AUTODL_PORT", "35299"))
USER = os.environ.get("AUTODL_USER", "root")
PASS = os.environ.get("AUTODL_PASS", "gpMW8alzDfoL")


def worker(idx, remote, total, n_streams, results):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20,
              banner_timeout=30, auth_timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    seg = total // n_streams
    start = idx * seg
    end = total if idx == n_streams - 1 else (idx + 1) * seg
    got = 0
    t0 = time.time()
    chunk = 1 << 20
    with sftp.open(remote, "rb") as rf:
        rf.seek(start)
        pos = start
        while pos < end:
            n = min(chunk, end - pos)
            data = rf.read(n)
            if not data:
                break
            got += len(data)
            pos += len(data)
    dt = time.time() - t0
    results[idx] = (got, dt)
    sftp.close()
    c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="/tmp/speedtest.bin")
    ap.add_argument("--streams", type=int, default=4)
    ap.add_argument("--mb", type=int, default=200)
    a = ap.parse_args()

    # 拿远端大小
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20,
              look_for_keys=False, allow_agent=False)
    total = c.open_sftp().stat(a.remote).st_size
    c.close()
    mb = min(a.mb * 2**20, total)
    print(f"remote={a.remote} size={total/2**20:.1f} MiB  测 {mb/2**20:.0f} MiB  "
          f"分 {a.streams} 流")

    results = {}
    t0 = time.time()
    ths = [threading.Thread(target=worker, args=(i, a.remote, mb, a.streams, results))
           for i in range(a.streams)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    wall = time.time() - t0
    got = sum(g for g, _ in results.values())
    print(f"总下载 {got/2**20:.1f} MiB  墙钟 {wall:.1f}s  合计 {got/2**20/wall:.2f} MiB/s")
    for i in sorted(results):
        g, dt = results[i]
        print(f"  stream {i}: {g/2**20:.1f} MiB / {dt:.1f}s = {g/2**20/dt:.2f} MiB/s")
    print(f"\n预估 23 GiB 回传耗时: {23*1024/(got/2**20/wall)/60:.1f} min")


if __name__ == "__main__":
    main()
