#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cloud_sync_base.py —— 本机 → AutoDL 增量同步基座（只传缺片/半片，支持断点续传）

缘起：远端下载被限速（aria2 x16 聚合 1.6MB/s、turbo 5.7MB/s），本机 8 线程
      13-44MB/s 且零机时。策略改为本机下全量 → 开机后只补远端缺口。

用法（远端已 shutdown 时会快速失败，先 autodl_power.py on）:
  # 1) 只看差异，不传
  python cloud_sync_base.py --dry
  # 2) 实际同步（默认 4 并发，断点续传）
  python cloud_sync_base.py --jobs 4
  # 3) 自定义目录
  python cloud_sync_base.py --local D:/.../train/lines/27b-kittyrev/base/Qwen3.8-27B \\
                            --remote /root/autodl-tmp/kitty-rev/base/Qwen3.8-27B

行为:
  * 按 (文件名, 字节数) 比对；远端缺失 或 尺寸不符 → 传
  * 远端已有部分字节（同名小文件）→ 从远端当前位置续传（append 模式）
  * 传完逐个复核远端 size，全等才打印 SYNC_OK
  * 任何一片失败 → 打印 FAILED 列表，退出码 2，可原命令重跑（幂等 + 续传）
"""
import argparse
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remote as R  # noqa: E402

DEF_LOCAL = r"D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/base/Qwen3.8-27B"
DEF_REMOTE = "/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B"

lock = threading.Lock()
done = {"bytes": 0, "files": 0}


def log(msg):
    with lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def remote_sizes(c, rdir):
    """返回 {basename: size}"""
    out, _ = R.run(c, f"cd {rdir} 2>/dev/null && stat -c '%s %n' * 2>/dev/null | sed 's|.*/||'", timeout=120)
    res = {}
    for line in (out or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            res[parts[1]] = int(parts[0])
    return res


def sftp_put_resume(c, lpath, rpath, offset, total):
    """从 offset 续传到远端 rpath（append 模式）。返回写入字节数。"""
    sftp = c.open_sftp()
    try:
        mode = "ab" if offset > 0 else "wb"
        with open(lpath, "rb") as lf, sftp.open(rpath, mode) as rf:
            lf.seek(offset)
            rf.set_pipelined(True)
            buf = 1 << 20
            while True:
                chunk = lf.read(buf)
                if not chunk:
                    break
                rf.write(chunk)
    finally:
        sftp.close()
    return total - offset


def transfer(local_dir, remote_dir, name, size, idx, total_files, total_bytes, base_done):
    c = R.connect(timeout=25)
    try:
        lpath = os.path.join(local_dir, name)
        rpath = f"{remote_dir}/{name}"
        # 远端现有字节（续传起点）
        out, _ = R.run(c, f"stat -c %s '{rpath}' 2>/dev/null || echo 0", timeout=60)
        try:
            have = int((out or "0").strip().splitlines()[-1])
        except Exception:
            have = 0
        if have > size:
            have = 0  # 远端更大 → 重传
        t0 = time.time()
        written = sftp_put_resume(c, lpath, rpath, have, size)
        dt = max(time.time() - t0, 1e-6)
        chk, _ = R.run(c, f"stat -c %s '{rpath}'", timeout=60)
        rsize = int((chk or "0").strip() or 0)
        ok = rsize == size
        with lock:
            done["bytes"] += written
            if ok:
                done["files"] += 1
            gb = (base_done + done["bytes"]) / 1073741824.0
        log(f"{'OK ' if ok else 'BAD'} {name} +{written/1048576:.0f}MiB "
            f"{written/dt/1048576:.1f}MB/s 远端={rsize} 累计={gb:.2f}GiB"
            f"{'' if ok else f' 期望={size}'}")
        return ok
    finally:
        try:
            c.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default=DEF_LOCAL)
    ap.add_argument("--remote", default=DEF_REMOTE)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--timeout-connect", type=int, default=25)
    a = ap.parse_args()

    if not os.path.isdir(a.local):
        print(f"[FATAL] 本地目录不存在: {a.local}")
        return 1
    local = {n: os.path.getsize(os.path.join(a.local, n))
             for n in sorted(os.listdir(a.local))
             if os.path.isfile(os.path.join(a.local, n))}
    if not local:
        print(f"[FATAL] 本地目录为空: {a.local}")
        return 1
    lsum = sum(local.values())
    log(f"本地 {len(local)} 文件 / {lsum/1073741824:.2f} GiB ← {a.local}")

    try:
        c = R.connect(timeout=a.timeout_connect)
    except Exception as e:
        print(f"[FATAL] 连不上远端（实例可能 shutdown）: {e}")
        return 3
    try:
        R.run(c, f"mkdir -p '{a.remote}'", timeout=60)
        rsizes = remote_sizes(c, a.remote)
    finally:
        try:
            c.close()
        except Exception:
            pass

    todo = []
    skip_bytes = 0
    for n, sz in local.items():
        rsz = rsizes.get(n)
        if rsz == sz:
            skip_bytes += sz
            continue
        # 尺寸不符但远端更小 → 续传：需要的前缀字节数
        need = sz if (rsz is None or rsz > sz) else (sz - rsz)
        todo.append((n, sz, need))
    log(f"远端已有匹配 {len(local)-len(todo)}/{len(local)} 文件（{skip_bytes/1073741824:.2f} GiB），"
        f"待传 {len(todo)} 文件 / {sum(t[2] for t in todo)/1073741824:.2f} GiB")
    for n, sz, need in todo:
        log(f"  NEED {n} 总{sz/1048576:.0f}MiB 缺{need/1048576:.0f}MiB")
    if a.dry:
        return 0
    if not todo:
        print("SYNC_OK (nothing to do)")
        return 0

    sems = threading.Semaphore(a.jobs)
    results = {}
    threads = []

    def wrap(item):
        n, sz, _need = item
        with sems:
            try:
                results[n] = transfer(a.local, a.remote, n, sz, 0, len(todo),
                                      sum(t[1] for t in todo), skip_bytes)
            except Exception as e:
                results[n] = False
                log(f"ERR {n}: {e}")

    t0 = time.time()
    for it in todo:
        t = threading.Thread(target=wrap, args=(it,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    dt = max(time.time() - t0, 1e-6)
    failed = [n for n, ok in results.items() if not ok]
    moved = done["bytes"] / 1048576.0
    log(f"耗时 {dt/60:.1f}min  实传 {moved:.0f}MiB  平均 {moved/dt:.1f}MB/s  "
        f"成功 {done['files']}/{len(todo)}")
    if failed:
        print("FAILED " + " ".join(failed))
        return 2
    print("SYNC_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
