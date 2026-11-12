#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dl_base_local.py —— 本机并行下载 Qwen/Qwen3.8-27B（hf-mirror，多连接分块）

为什么本机下：远端 4090 下载实测被镜像限速到 1.6-5 MB/s，2 小时机时就为下 42GB 不值；
本机单流 13.3 MB/s，不烧 GPU 机时。

用法：
  python dl_base_local.py --dest train/lines/27b-kittyrev/base/Qwen3.8-27B [--conn 8] [--files 4]
特性：断点续传（.part + 已完成即跳过）、每文件多线程 Range、按 API 清单逐个文件
"""
import argparse
import json
import os
import threading
import time
import urllib.request

MIRROR = "https://hf-mirror.com"
REPO = "Qwen/Qwen3.8-27B"
ALLOW = (".json", ".safetensors", ".jinja", ".txt")


def api_files():
    url = f"{MIRROR}/api/models/{REPO}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return [f["rfilename"] for f in d.get("siblings", []) if f["rfilename"].endswith(ALLOW)]


def head_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length") or 0)


def is_complete(path, size):
    """比"尺寸对"更强的完成判据（2026-10-29 血泪）：
    首轮 truncate 预分配的稀疏文件尺寸完全正确、内容全 0，上一版只比 size →
    直接 skip，5 片假完整（07/08/13/14/18，实测 zero_probes 3-4/4）。
    现在要求：size 相等 + safetensors 头可解析 + 中部 4KB 非全零。
    """
    if not os.path.exists(path) or os.path.getsize(path) != size:
        return False
    if not path.endswith(".safetensors"):
        return True
    try:
        with open(path, "rb") as f:
            n = int.from_bytes(f.read(8), "little")
            if not (0 < n < 200_000_000):
                return False
            json.loads(f.read(n))
            f.seek(size // 2)
            return any(f.read(4096))
    except Exception:
        return False


def verify_dir(dest, names=None):
    """对目录内每个 safetensors 做完整判据校验，返回坏文件列表。"""
    bad = []
    for n in sorted(os.listdir(dest)):
        if not n.endswith(".safetensors"):
            continue
        if names and n not in names:
            continue
        p = os.path.join(dest, n)
        sz = head_size(f"{MIRROR}/{REPO}/resolve/main/{n}")
        if not is_complete(p, sz):
            bad.append(n)
    return bad


def fetch_range(url, start, end, path, idx, report):
    """带重试的分块下载：按 part 文件当前大小续传"""
    p = f"{path}.part{idx}"
    need = end - start + 1
    for attempt in range(6):
        pos = os.path.getsize(p) if os.path.exists(p) else 0
        if pos >= need:
            return
        s0 = start + pos
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={s0}-{end}",
                                                       "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(p, "ab") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    report(len(b))
        except Exception as e:
            print(f"   [retry {attempt+1}] {os.path.basename(path)} part{idx}: {type(e).__name__}", flush=True)
            time.sleep(2 + attempt)
    if os.path.getsize(p) < need:
        raise RuntimeError(f"part {p} 未下完 {os.path.getsize(p)}/{need}")


def download(name, dest, conn):
    url = f"{MIRROR}/{REPO}/resolve/main/{name}"
    out = os.path.join(dest, name)
    size = head_size(url)
    if is_complete(out, size):
        print(f"[skip] {name} 已完整（size+头+中部均通过）")
        return
    if os.path.exists(out):
        # 必须连 .part* 一起删：首轮超时死掉留下的 .part 也是零内容满尺寸，
        # fetch_range 见 pos>=need 立刻返回 → 合并出来还是零文件（18 号片二次踩坑）
        print(f"[redo] {name} 尺寸对但内容坏（稀疏/全零），删 out + 全部 .part 重下")
        os.remove(out)
        d, b = os.path.split(out)
        for n in os.listdir(d):
            if n.startswith(b + ".part"):
                os.remove(os.path.join(d, n))
                print(f"   [redo] 清掉残留 part {n}")
    if size == 0:
        raise RuntimeError(f"no size: {name}")
    chunk = (size + conn - 1) // conn
    total = {"n": 0}
    lock = threading.Lock()

    def report(n):
        with lock:
            total["n"] += n

    parts = []
    for i in range(conn):
        s = i * chunk
        e = min(size - 1, (i + 1) * chunk - 1)
        p = f"{out}.part{i}"
        parts.append((s, e, p, i))

    t0 = time.time()
    threads = []
    for s, e, p, i in parts:
        t = threading.Thread(target=lambda s=s, e=e, p=p, i=i: fetch_range(url, s, e, out, i, report), daemon=True)
        t.start()
        threads.append(t)

    last = 0
    while any(t.is_alive() for t in threads):
        time.sleep(3)
        n = total["n"]
        sp = (n - last) / 3 / 1e6
        last = n
        print(f"   {name}: {n/1e9:.2f}/{size/1e9:.2f} GB  {sp:.1f} MB/s", flush=True)
    for t in threads:
        t.join()

    with open(out, "wb") as fo:
        for s, e, p, i in parts:
            with open(p, "rb") as fi:
                fo.write(fi.read())
            os.remove(p)
    ok = os.path.getsize(out) == size
    print(f"[done] {name} {os.path.getsize(out)/1e9:.2f} GB 一致={ok} 用时 {time.time()-t0:.0f}s", flush=True)
    if not ok:
        raise RuntimeError(f"size mismatch {name}")
    # 尺寸之外再做内容判据：残留零 part 会让"尺寸对、内容零"再次混过去
    if not is_complete(out, size):
        raise RuntimeError(f"content check failed（头/中部无效，可能有零 part）: {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                   "base", "Qwen3.8-27B"))
    ap.add_argument("--conn", type=int, default=8)
    ap.add_argument("--files", type=int, default=1, help="同时下几个文件（并发文件数）")
    ap.add_argument("--only", default="", help="只处理这些文件（逗号分隔文件名或序号码 如 7,8）")
    ap.add_argument("--verify", action="store_true", help="只校验，不下载")
    a = ap.parse_args()
    os.makedirs(a.dest, exist_ok=True)
    files = api_files()
    print(f"[list] {len(files)} 个文件 → {a.dest}")
    if a.only:
        want = set()
        for tok in a.only.replace(" ", "").split(","):
            if not tok:
                continue
            if tok.isdigit():
                want.update(n for n in files if f"-{int(tok):05d}-of-" in n)
            else:
                want.add(tok)
        files = [f for f in files if f in want]
        print(f"[only] 选中 {len(files)} 个: {files}")
    if a.verify:
        bad = verify_dir(a.dest, set(files) if a.only else None)
        print(f"[verify] 坏片 {len(bad)}: {bad if bad else '无'}")
        return 1 if bad else 0
    small = [f for f in files if not f.endswith(".safetensors")]
    big = [f for f in files if f.endswith(".safetensors")]
    for f in small:
        download(f, a.dest, 1)
    t0 = time.time()
    i = 0
    while i < len(big):
        batch = big[i:i + a.files]
        ths = []
        for f in batch:
            t = threading.Thread(target=download, args=(f, a.dest, a.conn))
            t.start()
            ths.append(t)
        for t in ths:
            t.join()
        i += a.files
    print(f"[ALL DONE] {len(big)} 片，总用时 {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    main()
