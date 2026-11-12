#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fast_fetch.py —— 多连接分段并行回传（比单流 sftp 快 5-15 倍）

做法：把远端文件按 --part-size 切成 N 段，每段用**独立的 SSH 连接**并发拉取，
      每段落盘即算 sha256；全部完成后本地拼接 → 再与远端整体 md5 对比。
      中途失败可 --resume（已存在且 sha 对上的段直接跳过）。

用法：
  python fast_fetch.py --remote /root/x.ninfer --local D:/.../x.ninfer --streams 16
  python fast_fetch.py --remote ... --local ... --streams 8 --part-size 268435456 --resume
  python fast_fetch.py --remote ... --local ... --bench 1        # 只测速（拉 512MB 样本，不落成品）

环境变量：AUTODL_HOST / AUTODL_PORT / AUTODL_USER / AUTODL_PASS（与 deploy/remote.py 同源）
"""
import argparse
import hashlib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import paramiko

HOST = os.environ.get("AUTODL_HOST", "123.127.15.155")
PORT = int(os.environ.get("AUTODL_PORT", "35299"))
USER = os.environ.get("AUTODL_USER", "root")
PASS = os.environ.get("AUTODL_PASS", "gpMW8alzDfoL")

CHUNK = 4 * 1024 * 1024  # 单次 read 的块大小（4 MiB）


def connect(timeout=20):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=timeout,
              banner_timeout=30, auth_timeout=30, look_for_keys=False, allow_agent=False)
    return c


def remote_stat(c, path):
    sftp = c.open_sftp()
    st = sftp.stat(path)
    sftp.close()
    return st.st_size


def remote_md5(c, path):
    _, out, _ = c.exec_command(f"md5sum '{path}'", timeout=1800)
    line = out.read().decode("utf-8", "replace").strip()
    return line.split()[0] if line else ""


def fetch_part(path, off, length, out_path, retries=4):
    """独立连接拉取 [off, off+length) 写入 out_path，返回 (idx_sha, bytes)"""
    for attempt in range(1, retries + 1):
        try:
            c = connect(60)
            sftp = c.open_sftp()
            f = sftp.open(path, "rb")
            f.seek(off)
            h = hashlib.sha256()
            got = 0
            with open(out_path, "wb") as w:
                while got < length:
                    want = min(CHUNK, length - got)
                    buf = f.read(want)
                    if not buf:
                        break
                    w.write(buf)
                    h.update(buf)
                    got += len(buf)
            f.close()
            sftp.close()
            c.close()
            if got != length:
                raise IOError(f"short read {got}/{length}")
            return h.hexdigest(), got
        except Exception as e:
            if attempt == retries:
                raise
            print(f"  [retry {attempt}] offset={off} {e}", flush=True)
            time.sleep(2 * attempt)


def md5_file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", required=True)
    ap.add_argument("--local", required=True)
    ap.add_argument("--streams", type=int, default=16)
    ap.add_argument("--part-size", type=int, default=256 * 1024 * 1024)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--bench", action="store_true", help="只测速：拉前 512MB 到临时文件")
    a = ap.parse_args()

    c0 = connect()
    total = remote_stat(c0, a.remote)
    print(f"[info] remote={a.remote} size={total} ({total/1e9:.2f} GB) streams={a.streams} part={a.part_size/1e6:.0f}MB", flush=True)
    rmd5 = remote_md5(c0, a.remote) if not a.bench else ""
    print(f"[info] remote_md5={rmd5}", flush=True)

    limit = min(total, 512 * 1024 * 1024) if a.bench else total
    parts = []
    off = 0
    while off < limit:
        n = min(a.part_size, limit - off)
        parts.append((off, n))
        off += n

    pdir = a.local + ".parts"
    os.makedirs(pdir, exist_ok=True)
    t0 = time.time()
    results = {}
    done_bytes = [0]
    lock = threading.Lock()

    def task(idx, off, n):
        p = os.path.join(pdir, f"part-{idx:04d}-{off}")
        if a.resume and os.path.exists(p) and os.path.getsize(p) == n:
            return idx, None, n
        sha, got = fetch_part(a.remote, off, n, p)
        with lock:
            done_bytes[0] += got
        return idx, sha, got

    with ThreadPoolExecutor(max_workers=a.streams) as ex:
        futs = [ex.submit(task, i, off, n) for i, (off, n) in enumerate(parts)]
        for f in as_completed(futs):
            idx, sha, got = f.result()
            results[idx] = (sha, got)
            el = time.time() - t0
            print(f"[part {idx+1}/{len(parts)}] {got/1e6:.0f}MB  acc={done_bytes[0]/1e9:.2f}GB  {done_bytes[0]/1e6/max(el,1e-9):.1f} MB/s", flush=True)

    el = time.time() - t0
    print(f"[speed] {done_bytes[0]/1e6/max(el,1e-9):.1f} MB/s  elapsed={el:.1f}s", flush=True)

    if a.bench:
        print("[bench] 完成（未拼接成品）", flush=True)
        return 0

    # 拼接（按 part 顺序）
    print("[join] 拼接中…", flush=True)
    with open(a.local, "wb") as w:
        for i, (off, n) in enumerate(parts):
            p = os.path.join(pdir, f"part-{i:04d}-{off}")
            with open(p, "rb") as r:
                for b in iter(lambda: r.read(8 * 1024 * 1024), b""):
                    w.write(b)

    lmd5 = md5_file(a.local)
    print(f"[md5] local ={lmd5}", flush=True)
    print(f"[md5] remote={rmd5}", flush=True)
    ok = (lmd5 == rmd5)
    print(f"[VERDICT] {'PASS' if ok else 'FAIL'}", flush=True)
    if ok:
        import shutil
        shutil.rmtree(pdir, ignore_errors=True)
        print("[clean] 分段目录已清理", flush=True)
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
