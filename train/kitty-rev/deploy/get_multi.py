#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""get_multi.py —— 多流并发 + 断点续传的大文件下载器

为什么需要它：
    AutoDL 侧对**每条 SSH 连接**限速约 0.7 MiB/s（实测 1/4/8/16/32 流分别 0.70/2.49/5.13/8.8/18 MiB/s）。
    单流下 31.6 GiB 要 12 小时；32 流约 30 分钟。本机带宽不是瓶颈（夸克网盘 30-40 MB/s）。

用法：
    python get_multi.py --remote /root/autodl-tmp/kitty-rev/pack.tar \
                        --local  D:/.../train/local-pack/pack.tar --streams 32

    ⚠ 流数选择（2026-10-22 实测，AutoDL bjb1 → 本地）：
      32 流：起步 18 MiB/s，但跑久会衰减到 10，且**中断后拼接会错位**（md5 不符）
      16 流：全程稳定 10-11 MiB/s，27.9 分钟传完 16 G，md5 一次过  ← 推荐
       8 流：只有 2.3 MiB/s（尤其与别的下载并发时）
      ⇒ 并发不是越高越好，16 流是该链路的稳定点；重传必须 --reset-parts 干净起跑

断点续传：
    每段写 <local>.partNNN；重跑时按已存在字节数 seek 续传；全部完成后合并并校验 md5。
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time

import paramiko

# Windows 控制台默认 GBK；输出里一旦出现 ✓/✗ 或中文就会 UnicodeEncodeError 直接崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = os.environ.get("AUTODL_HOST", "connect.bjb1.seetacloud.com")
PORT = int(os.environ.get("AUTODL_PORT", "35299"))
USER = os.environ.get("AUTODL_USER", "root")
PASS = os.environ.get("AUTODL_PASS", "gpMW8alzDfoL")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20,
              banner_timeout=30, auth_timeout=30, look_for_keys=False, allow_agent=False)
    return c


def remote_size_and_md5(remote):
    c = connect()
    sftp = c.open_sftp()
    size = sftp.stat(remote).st_size
    sftp.close()
    # md5 在远端算（一次 IO，比下载后本地算省一半时间）
    chan = c.get_transport().open_session()
    chan.exec_command(f"md5sum {remote} 2>/dev/null | cut -d' ' -f1")
    md5 = chan.makefile("r").read().strip()
    # paramiko 的 makefile() 在某些版本返回 bytes（不受 "r" 影响），必须显式 decode，
    # 否则 md5 是 bytes → write_meta 的 json.dump 抛 TypeError（2026-10-22 实测）
    if isinstance(md5, bytes):
        md5 = md5.decode("utf-8", "replace")
    c.close()
    return size, md5


META_V = 1


def meta_path(local):
    return local + ".meta.json"


def read_meta(local):
    try:
        with open(meta_path(local), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_meta(local, meta):
    with open(meta_path(local), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


def part_paths(local, n):
    return [f"{local}.part{i:03d}" for i in range(n)]


def wipe_parts(local):
    """删掉所有 <local>.partNNN（旧布局 / 换源时用，删完要回报个数）。"""
    d, base = os.path.dirname(local) or ".", os.path.basename(local)
    n = 0
    for f in os.listdir(d):
        if f.startswith(base + ".part"):
            try:
                os.unlink(os.path.join(d, f))
                n += 1
            except OSError:
                pass
    return n


def fetch_segment(idx, remote, total, n_streams, local_base, slot_bytes, results, lock, done_bytes,
                  retries=4):
    part = f"{local_base}.part{idx:03d}"
    seg_start = idx * slot_bytes
    seg_end = total if idx == n_streams - 1 else (idx + 1) * slot_bytes
    seg_len = seg_end - seg_start

    for attempt in range(1, retries + 1):
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        if have > seg_len:
            have = 0
        if have == seg_len:
            results[idx] = seg_len
            with lock:
                done_bytes[0] += seg_len
            return
        before = have
        try:
            c = connect()
            sftp = c.open_sftp()
            with sftp.open(remote, "rb") as rf, open(part, "ab" if have else "wb") as lf:
                rf.seek(seg_start + have)
                pos = have
                chunk = 1 << 20
                while pos < seg_len:
                    n = min(chunk, seg_len - pos)
                    data = rf.read(n)
                    if not data:
                        # 远端提前 EOF（文件名/大小都对，内容短）：过去这里是 break，
                        # 然后当成功返回 → 合并时 truncate 补零 → 只有 md5 能发现，
                        # --skip-md5 下就是静默损坏。短读必须当错误，走重试/FAIL。
                        raise IOError(f"远端提前 EOF：seg {idx} 只读到 {pos}/{seg_len} 字节")
                    lf.write(data)
                    pos += len(data)
                    with lock:
                        done_bytes[0] += len(data)
            sftp.close()
            c.close()
            got = os.path.getsize(part)
            if got != seg_len:
                raise IOError(f"seg {idx} 落盘 {got} != 期望 {seg_len}（合并前必须相等）")
            results[idx] = got
            return
        except Exception as e:
            # 超时/断连：已完成字节已落盘，下一轮从这里续；只把本轮增量退回计数
            got_now = os.path.getsize(part) if os.path.isfile(part) else 0
            with lock:
                done_bytes[0] -= max(got_now - before, 0)
            if attempt == retries:
                results[idx] = f"ERR after {retries} tries: {type(e).__name__}: {e}"
                return
            time.sleep(2 * attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", required=True)
    ap.add_argument("--local", required=True)
    ap.add_argument("--streams", type=int, default=32)
    ap.add_argument("--skip-md5", action="store_true")
    ap.add_argument("--reset-parts", action="store_true",
                    help="丢弃已有 .partNNN 重下（布局/源变化被拒后用它）")
    a = ap.parse_args()

    local = os.path.abspath(a.local)
    os.makedirs(os.path.dirname(local) or ".", exist_ok=True)

    print(f"[probe] {a.remote} …", flush=True)
    total, rmd5 = remote_size_and_md5(a.remote)
    print(f"[probe] size={total/2**30:.2f} GiB  md5={rmd5 or 'n/a'}", flush=True)

    # 已完整下载过？
    if os.path.isfile(local) and os.path.getsize(local) == total:
        if not a.skip_md5 and rmd5:
            h = hashlib.md5()
            with open(local, "rb") as f:
                for b in iter(lambda: f.read(1 << 22), b""):
                    h.update(b)
            if h.hexdigest() == rmd5:
                print(f"[skip] 已存在且 md5 一致：{local}")
                return 0
            print("[warn] 已存在但 md5 不符，重新下载")
        else:
            print(f"[skip] 已存在且大小一致：{local}")
            return 0

    n = a.streams
    slot = (total + n - 1) // n

    # ---- 断点布局指纹（S3：换 --streams 后旧 part 的字节边界与新 slot 不符） ----
    want = {"v": META_V, "remote": a.remote, "size": total, "md5": rmd5, "streams": n, "slot": slot}
    have_parts = any(os.path.isfile(p) for p in part_paths(local, max(n, 64)))
    old = read_meta(local)
    if a.reset_parts:
        k = wipe_parts(local)
        print(f"[reset] --reset-parts：删掉 {k} 个旧 part，从头下", flush=True)
    elif have_parts:
        if old != want:
            diff = [k for k in want if (old or {}).get(k) != want[k]]
            print(f"[FATAL] 发现旧 part，但布局/源与本次不一致（差异字段：{diff}）", flush=True)
            print(f"        旧: {old}", flush=True)
            print(f"        新: {want}", flush=True)
            print("        混用会产出「大小对、内容错」的文件（只有 md5 能发现，--skip-md5 下静默）。\n"
                  "        用 --reset-parts 丢弃旧 part 重下；若只是上次中断且参数没变，直接重跑即可。",
                  flush=True)
            return 1
        print(f"[resume] 布局指纹一致，从现有 part 续传（{n} 段 × {slot/2**20:.1f} MiB）", flush=True)
    write_meta(local, want)

    results = {}
    done = [0]
    lock = threading.Lock()
    t0 = time.time()

    def progress():
        while any(t.is_alive() for t in ths):
            time.sleep(5)
            with lock:
                d = done[0]
            spd = d / max(time.time() - t0, 1e-6) / 2**20
            pct = d / total * 100
            eta = (total - d) / max(spd * 2**20, 1) / 60
            print(f"  {pct:5.1f}%  {d/2**30:6.2f}/{total/2**30:.2f} GiB  "
                  f"{spd:5.2f} MiB/s  ETA {eta:.1f} min", flush=True)

    ths = [threading.Thread(target=fetch_segment,
                            args=(i, a.remote, total, n, local, slot, results, lock, done))
           for i in range(n)]
    mon = threading.Thread(target=progress, daemon=True)
    for t in ths:
        t.start()
    mon.start()
    for t in ths:
        t.join()

    errs = [(i, v) for i, v in results.items() if isinstance(v, str)]
    if errs:
        print(f"[FATAL] {len(errs)} 段失败，重跑本命令会从断点续传：")
        for i, v in errs[:5]:
            print(f"  seg {i}: {v}")
        return 1

    # 合并（写入预分配文件，避免再占一份磁盘）
    # 合并前逐个核 size：短一字节也不能进来 —— truncate 会把缺的部分留成零，
    # 而零填充只有 md5 能发现（--skip-md5 下就是静默损坏）。
    bad = []
    for i in range(n):
        part = f"{local}.part{i:03d}"
        exp = total - i * slot if i == n - 1 else slot
        got_p = os.path.getsize(part) if os.path.isfile(part) else -1
        if got_p != exp:
            bad.append((i, got_p, exp))
    if bad:
        print(f"[FATAL] {len(bad)} 段长度不对，拒绝合并（会留零填充）：")
        for i, g, e in bad[:5]:
            print(f"  seg {i}: {g} != {e}")
        return 1

    print(f"[merge] {n} 段 → {local}", flush=True)
    with open(local, "wb") as out:
        out.truncate(total)
        for i in range(n):
            part = f"{local}.part{i:03d}"
            with open(part, "rb") as pf:
                while True:
                    b = pf.read(1 << 22)
                    if not b:
                        break
                    out.write(b)
    for i in range(n):
        try:
            os.unlink(f"{local}.part{i:03d}")
        except OSError:
            pass

    got = os.path.getsize(local)
    if got != total:
        print(f"[FATAL] 合并后大小不符 {got} != {total}")
        return 1

    if not a.skip_md5 and rmd5:
        print("[md5] 校验中 …", flush=True)
        h = hashlib.md5()
        with open(local, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        ok = h.hexdigest() == rmd5
        print(f"[md5] {'MATCH' if ok else 'MISMATCH'}  {h.hexdigest()[:16]}  (remote {rmd5[:16]})")
        if not ok:
            return 1

    # 收尾：meta 只描述「进行中的分片」，完成后删掉，避免下次误判为可续传布局
    try:
        os.unlink(meta_path(local))
    except OSError:
        pass

    print(f"[done] {local}  {total/2**30:.2f} GiB  耗时 {(time.time()-t0)/60:.1f} min"
          f"  平均 {total/2**20/max(time.time()-t0,1):.2f} MiB/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
