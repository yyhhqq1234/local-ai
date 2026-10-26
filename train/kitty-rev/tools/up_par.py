#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""up_par.py —— 多线程分块上传（每块独立连接，逐块校验远端 size，坏块重传）
用法：python tools/up_par.py <本地文件> <云端路径> [--workers 8] [--mb 200]
"""
import argparse, os, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from deploy import remote  # noqa  # reuse paramiko config? fallback below


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--mb", type=int, default=200)
    a = ap.parse_args()

    import paramiko
    HOST = os.environ.get("AUTODL_HOST", "123.127.15.155")
    PORT = int(os.environ.get("AUTODL_PORT", "35299"))
    USER = os.environ.get("AUTODL_USER", "root")
    PASS = os.environ.get("AUTODL_PASS", "gpMW8alzDfoL")

    def conn():
        c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30,
                  banner_timeout=40, auth_timeout=40, look_for_keys=False, allow_agent=False)
        return c, c.open_sftp()

    size = os.path.getsize(a.src)
    chunk = a.mb * 1024 * 1024
    n = (size + chunk - 1) // chunk
    base = os.path.basename(a.dst)
    d = os.path.dirname(a.dst)
    print(f"[info] size={size} chunks={n} workers={a.workers}", flush=True)

    c0, s0 = conn()
    s0.stat(d) if True else None
    c0.exec_command(f"mkdir -p {d}")[1].read()
    c0.exec_command(f"rm -f {d}/{base} {d}/{base}.c.*")[1].read()
    c0.close()

    lock = threading.Lock(); done = [0]; fail = []

    def one(i):
        off = i * chunk; ln = min(chunk, size - off)
        rpath = f"{d}/{base}.c.{i:05d}"
        for attempt in range(4):
            try:
                c, s = conn()
                try:
                    st = s.stat(rpath)
                    if st.st_size == ln:
                        with lock: done[0] += 1
                        return
                except IOError:
                    pass
                with open(a.src, "rb") as f:
                    f.seek(off)
                    data = f.read(ln)
                with s.open(rpath, "wb") as r:
                    r.set_pipelined(True)
                    r.write(data)
                st = s.stat(rpath)
                if st.st_size != ln:
                    raise IOError(f"size {st.st_size}!={ln}")
                s.close(); c.close()
                with lock:
                    done[0] += 1
                    if done[0] % 5 == 0:
                        print(f"    {done[0]}/{n}", flush=True)
                return
            except Exception as e:
                if attempt == 3:
                    with lock: fail.append((i, str(e)))
                time.sleep(2)
        return

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, range(n)))

    if fail:
        print(f"[FAIL] {len(fail)} 块失败: {fail[:3]}", flush=True)
        return 2

    c, s = conn()
    cmd = f"cd {d} && cat $(ls {base}.c.* | sort) > {base} && stat -c%s {base} && rm -f {base}.c.*"
    out = c.exec_command(cmd)[1].read().decode().strip()
    c.close()
    print(f"[join] remote size={out}  local={size}", flush=True)
    return 0 if out == str(size) else 3


if __name__ == "__main__":
    sys.exit(main())
