#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""up_par.py —— 多连接并行上传测速 / 实传（本机 → AutoDL）

单流实测只有 2.0 MB/s（89.3MB/45s），疑似 SSH 单连接加解密上限而非带宽，
故这里用 N 条独立 SFTP 连接同时上传，测聚合带宽。

用法：
  # 测速：把同一文件切成 N 段各传一份（小文件即可，验证聚合）
  python up_par.py --speed --src <本地文件> --mb 20 --streams 8

  # 实传：把本地目录下的文件按文件级并行上传到远端目录（跳过远端已完整的）
  python up_par.py --dir <本地目录> --remote <远端目录> --streams 8
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remote as R


def fix_remote(p):
    """MSYS2 会把以 / 开头的裸参数改写成 Windows 路径
    （实测 /root/autodl-tmp/... 变成 C:/Users/.../bash/2.56.0.2/root/autodl-tmp/...）。
    远端 POSIX 路径必须还原：从第一个 /root/ 起截断。"""
    i = p.find("/root/")
    if i > 0:
        return p[i:]
    return p


def up_one(lpath, rpath, offset=0, size=None, append=False):
    c = R.connect(timeout=25)
    try:
        sftp = c.open_sftp()
        try:
            t0 = time.time()
            mode = "ab" if append else "wb"
            with open(lpath, "rb") as lf:
                lf.seek(offset)
                with sftp.open(rpath, mode) as rf:
                    rf.set_pipelined(True)
                    left = size if size is not None else os.path.getsize(lpath) - offset
                    while left > 0:
                        b = lf.read(min(1 << 20, left))
                        if not b:
                            break
                        rf.write(b)
                        left -= len(b)
            return time.time() - t0
        finally:
            sftp.close()
    finally:
        try:
            c.close()
        except Exception:
            pass


def remote_size(rpath):
    for _try in range(3):
        v = _remote_size_once(rpath)
        if v >= 0:
            return v
        time.sleep(1.5)
    return -2


def _remote_size_once(rpath):
    c = R.connect(timeout=25)
    try:
        _, out = R.run(c, f"stat -c %s '{rpath}' 2>/dev/null || echo -1", timeout=40, quiet=True)
        try:
            return int((out or "-1").strip().splitlines()[-1])
        except Exception:
            return -1
    finally:
        try:
            c.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", action="store_true")
    ap.add_argument("--src")
    ap.add_argument("--dir")
    ap.add_argument("--remote")
    ap.add_argument("--mb", type=int, default=20)
    ap.add_argument("--streams", type=int, default=8)
    ap.add_argument("--resume", action="store_true", help="按远端已有字节续传/跳过")
    a = ap.parse_args()
    if getattr(a, "remote", None):
        a.remote = fix_remote(a.remote)

    if a.speed:
        if not a.src or not os.path.isfile(a.src):
            raise SystemExit("[FATAL] --speed 需要 --src 本地文件")
        piece = a.mb * 1024 * 1024
        n = a.streams
        ths = []
        t0 = time.time()

        def w(i):
            up_one(a.src, f"/root/autodl-tmp/_up_spd_{i}.bin", offset=i * piece, size=piece)

        for i in range(n):
            t = threading.Thread(target=w, args=(i,), daemon=True)
            t.start()
            ths.append(t)
        for t in ths:
            t.join()
        dt = time.time() - t0
        tot = n * piece / 1048576
        print(f"[speed] {tot:.0f} MB / {dt:.1f}s = {tot/dt:.2f} MB/s  ({n} 路并发)")
        return 0

    if not a.dir or not a.remote:
        raise SystemExit("[FATAL] --dir 需要 --remote")
    files = [f for f in sorted(os.listdir(a.dir)) if os.path.isfile(os.path.join(a.dir, f))]
    print(f"[plan] {len(files)} 文件 → {a.remote}  并发 {a.streams}")
    lock = threading.Lock()
    idx = {"i": 0}
    done = []

    def worker():
        while True:
            with lock:
                if idx["i"] >= len(files):
                    return
                f = files[idx["i"]]
                idx["i"] += 1
            lp = os.path.join(a.dir, f)
            sz = os.path.getsize(lp)
            rp = f"{a.remote}/{f}"
            t = time.time()
            try:
                off, app = 0, False
                if a.resume:
                    rsz = remote_size(rp)
                    if rsz == -2:
                        raise RuntimeError("stat 连续失败，远端大小未知，拒绝写入（避免 wb 截断）")
                    if rsz == sz:
                        with lock:
                            done.append((f, 0, time.time() - t, True))
                        print(f"  SKIP {f} 远端已完整", flush=True)
                        continue
                    if 0 < rsz < sz:
                        off, app = rsz, True
                up_one(lp, rp, offset=off, append=app)
                with lock:
                    done.append((f, sz - off, time.time() - t, True))
                print(f"  OK  {f} {(sz-off)/1048576:.0f}MB {time.time()-t:.0f}s"
                      f"{f' (续传自 {off/1048576:.0f}MB)' if off else ''}", flush=True)
            except Exception as e:
                with lock:
                    done.append((f, sz, time.time() - t, False))
                print(f"  ERR {f}: {e}", flush=True)

    t0 = time.time()
    ths = [threading.Thread(target=worker, daemon=True) for _ in range(a.streams)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    dt = time.time() - t0
    ok = [d for d in done if d[3]]
    bad = [d for d in done if not d[3]]
    tot = sum(d[1] for d in ok) / 1048576
    print(f"[done] 成功 {len(ok)}/{len(done)}  {tot:.0f}MB / {dt/60:.1f}min = {tot/max(dt,1e-6):.2f} MB/s")
    if bad:
        print("FAILED " + " ".join(d[0] for d in bad))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
