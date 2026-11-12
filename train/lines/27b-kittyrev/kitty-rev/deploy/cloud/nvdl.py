#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""nvdl.py —— 远端并行拉取 torch cu128 的 nvidia 依赖轮子（断点续传 + 多线程）

背景：pip 本体在 AutoDL 上下 700MB 级 wheel 会卡死（aliyun / tuna 都实测卡在 50% 不动）。
对策：自己解析 simple index 取直链，curl 风格 Range 续传，6 并发，落 /root/nvwhl，
      再用 pip --no-index --find-links 本地装。

用法（远端）：
  /root/miniconda3/bin/python /root/autodl-tmp/cloud/nvdl.py fetch
  /root/miniconda3/bin/python /root/autodl-tmp/cloud/nvdl.py install
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import time

MIRRORS = [
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "http://mirrors.aliyun.com/pypi/simple",
]
OUT = "/root/nvwhl"
PY = "/root/miniconda3/bin/python"

# torch 2.9.1+cu128 的 METADATA 精确锁定（见 wheel Requires-Dist）
NEED = [
    ("nvidia-cuda-nvrtc-cu12", "12.8.93"),
    ("nvidia-cuda-runtime-cu12", "12.8.90"),
    ("nvidia-cuda-cupti-cu12", "12.8.90"),
    ("nvidia-cudnn-cu12", "9.10.2.21"),
    ("nvidia-cublas-cu12", "12.8.4.1"),
    ("nvidia-cufft-cu12", "11.3.3.83"),
    ("nvidia-curand-cu12", "10.3.9.90"),
    ("nvidia-cusolver-cu12", "11.7.3.90"),
    ("nvidia-cusparse-cu12", "12.5.8.93"),
    ("nvidia-cusparselt-cu12", "0.7.1"),
    ("nvidia-nccl-cu12", "2.27.5"),
    ("nvidia-nvshmem-cu12", "3.3.20"),
    ("nvidia-nvtx-cu12", "12.8.90"),
    ("nvidia-nvjitlink-cu12", "12.8.93"),
    ("nvidia-cufile-cu12", "1.13.1.3"),
    ("triton", "3.5.1"),
]


def get(url, timeout=60):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "pip/24.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def pick(pkg, ver):
    """从 simple index 里挑该版本的 linux x86_64 轮子直链"""
    for m in MIRRORS:
        try:
            html = get(f"{m}/{pkg}/")
        except Exception as e:
            print(f"  [idx-skip] {m} {pkg}: {type(e).__name__}")
            continue
        cands = re.findall(r'href="([^"#]+)[^"]*"', html)
        hit = [c for c in cands
               if f"-{ver}-" in c and c.endswith(".whl")
               and ("x86_64" in c or "-none-any.whl" in c)
               and "aarch64" not in c and "arm64" not in c]
        # 优先 manylinux_2_27/2_28，其次其它
        hit.sort(key=lambda c: (("manylinux_2_28" not in c), ("manylinux_2_27" not in c)))
        if hit:
            u = hit[0]
            if u.startswith("http"):
                return u
            import urllib.parse as up
            if u.startswith("/"):
                return up.urljoin(m.split("/simple")[0] + "/", u)
            return up.urljoin(m + f"/{pkg}/", u)
    return None


def download(url, dest, tries=6):
    import urllib.request
    base = dest + ".part"
    for i in range(tries):
        have = os.path.getsize(base) if os.path.exists(base) else 0
        hdr = {"User-Agent": "pip/24.0"}
        if have:
            hdr["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=60) as r:
                mode = "ab" if (have and r.status == 206) else "wb"
                if mode == "wb":
                    have = 0
                t0, got = time.time(), 0
                with open(base, mode) as f:
                    while True:
                        c = r.read(1 << 20)
                        if not c:
                            break
                        f.write(c)
                        got += len(c)
            sz = os.path.getsize(base)
            os.replace(base, dest)
            return True, sz, got / max(time.time() - t0, 1e-6)
        except Exception as e:
            print(f"    [retry {i+1}/{tries}] {os.path.basename(dest)} {type(e).__name__}")
            time.sleep(2)
    return False, 0, 0


def fetch():
    os.makedirs(OUT, exist_ok=True)
    todo = []
    for pkg, ver in NEED:
        # 已有完整文件就跳
        for f in os.listdir(OUT):
            if f.startswith(pkg.replace("-", "_")) and f.endswith(".whl"):
                print(f"[have] {f}")
                break
        else:
            u = pick(pkg, ver)
            if not u:
                print(f"[MISS] {pkg}=={ver} 未找到直链")
                continue
            todo.append((pkg, ver, u, os.path.join(OUT, os.path.basename(u).split("#")[0])))
    print(f"[plan] {len(todo)} 个待下")
    ok = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(download, u, d): (p, v) for p, v, u, d in todo}
        for fu in cf.as_completed(futs):
            p, v = futs[fu]
            good, sz, sp = fu.result()
            print(f"[{'OK' if good else 'FAIL'}] {p}=={v} {sz/2**20:.0f}MiB {sp/2**20:.1f}MiB/s", flush=True)
            ok += 1 if good else 0
    print(f"[done] {ok}/{len(todo)}")


def install():
    names = []
    for pkg, ver in NEED:
        for f in os.listdir(OUT):
            if f.startswith(pkg.replace("-", "_")) and f.endswith(".whl"):
                names.append(f"{pkg}=={ver}")
                break
    torch_whl = "/root/torch-2.9.1+cu128-cp312-cp312-manylinux_2_28_x86_64.whl"
    cmd = [PY, "-m", "pip", "install", "--no-cache-dir", "--no-index",
           "--find-links", OUT, torch_whl] + names
    print("[install]", " ".join(cmd[:8]), f"... (+{len(names)} deps)")
    r = subprocess.run(cmd)
    print("[install] rc=", r.returncode)
    return r.returncode


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if a == "fetch":
        fetch()
    elif a == "install":
        sys.exit(install())
    else:
        print(__doc__)
