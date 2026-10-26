#!/usr/bin/env python3
"""dl_base_fast.py —— 多段并发拉取 HF 基座（默认 32 段/片 × 32 并发，云端 128 核可调）

设计要点（来自 2026-10-22..24 的实测教训）：
  · hf-mirror 对长连接限速、对单次 range 请求不限 → 多段叠加才快
  · 会单点死的域名现象像"限速" → 先用 config.json 做双域名同命令对比，选通的
  · 逐片：段并发下载 → 按序拼接 → 校验 size/结构 → 删段文件（磁盘峰值 = 1 片 × 2）
  · 失败重试 3 次，日志落盘，不吞错误

用法（云端）：
  python3 tools/dl_base_fast.py --out /root/autodl-tmp/kitty-rev/base/Huihui \
      --list /root/autodl-tmp/kitty-rev/tmp/_base/shards.txt --conc 32 --seg-mb 32
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HOSTS = ["huggingface.co", "hf-mirror.net", "hf-mirror.com"]
REPO = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"
SMALL = ["config.json", "generation_config.json", "model.safetensors.index.json",
         "tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt",
         "special_tokens_map.json", "chat_template.jinja", "preprocessor_config.json",
         "video_preprocessor_config.json", "processor_config.json", "added_tokens.json"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def curl(url, out, byte_range=None, retries=3, timeout=1800):
    for i in range(retries):
        cmd = ["curl", "-4", "-sS", "-L", "--connect-timeout", "20",
               "--max-time", str(timeout), "-o", out]
        if byte_range:
            cmd += ["-r", byte_range]
        cmd.append(url)
        r = subprocess.run(cmd)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return True
        time.sleep(2 + i * 3)
    return False


def probe_hosts():
    """用 config.json 探活；必须带 -L（huggingface.co 会 302 到 CAS CDN）。
    2026-10-24 实测：turbo 单流 4.4 MB/s、8 并发 AGG 18.4 MB/s；
    hf-mirror.net 8 并发 AGG 19.6 MB/s；单流都被限到 4-5 MB/s ⇒ 必须多段。"""
    for h in HOSTS:
        t0 = time.time()
        url = f"https://{h}/{REPO}/resolve/main/config.json"
        r = subprocess.run(["curl", "-4", "-sL", "-o", "/dev/null", "--max-time", "12",
                            "-w", "%{http_code}", url], capture_output=True, text=True)
        code = (r.stdout or "").strip()
        dt = time.time() - t0
        log(f"[probe] {h:<18} http={code} {dt:.1f}s")
        if code in ("200", "206", "302"):
            return h
    return None


def safetensors_ok(path, want_size):
    """结构自检：8 + header_len + max(data_offsets) == filesize"""
    try:
        if os.path.getsize(path) != want_size:
            return False, f"size {os.path.getsize(path)} != {want_size}"
        with open(path, "rb") as f:
            (n,) = struct.unpack("<Q", f.read(8))
            if n <= 0 or n > 200 << 20:
                return False, f"header_len {n} 异常"
            hdr = json.loads(f.read(n).decode("utf-8"))
        hdr.pop("__metadata__", None)
        max_end = max(v["data_offsets"][1] for v in hdr.values())
        if 8 + n + max_end != want_size:
            return False, f"struct {8+n+max_end} != {want_size}"
        return True, f"{len(hdr)} tensors"
    except Exception as e:
        return False, f"exc {type(e).__name__}: {e}"


def fetch_shard(host, name, want, outdir, seg_mb, conc, logpath):
    dst = os.path.join(outdir, name)
    if os.path.exists(dst):
        ok, why = safetensors_ok(dst, want)
        if ok:
            log(f"[skip] {name} 已完整 ({why})")
            return True
        log(f"[redo] {name} 现存文件不合格: {why} → 重下")
        os.remove(dst)

    seg = seg_mb << 20
    nseg = max(1, (want + seg - 1) // seg)
    parts = []
    jobs = []
    for i in range(nseg):
        a = i * seg
        b = min(a + seg, want) - 1
        p = f"{dst}.seg{i:04d}"
        parts.append(p)
        jobs.append((i, a, b, p))

    url = f"https://{host}/{REPO}/resolve/main/{name}"
    log(f"[shard] {name} {want:,} B → {nseg} 段 × {seg_mb} MB, 并发 {conc}")
    t0 = time.time()
    done_bytes = 0
    fail = []
    with ThreadPoolExecutor(max_workers=conc) as ex:
        futs = {ex.submit(curl, url, p, f"{a}-{b}"): (i, a, b, p) for i, a, b, p in jobs}
        for k, fut in enumerate(as_completed(futs), 1):
            i, a, b, p = futs[fut]
            ok = fut.result()
            want_len = b - a + 1
            got_len = os.path.getsize(p) if os.path.exists(p) else 0
            if not ok or got_len != want_len:
                fail.append((i, got_len, want_len))
            else:
                done_bytes += got_len
            if k % 8 == 0 or k == nseg:
                el = time.time() - t0
                rate = done_bytes / el / 1e6 if el > 0 else 0
                log(f"   seg {k}/{nseg}  {done_bytes/1e6:.0f} MB  {rate:.1f} MB/s  "
                    f"ETA {(done_bytes and (want-done_bytes)/max(rate*1e6,1)/60) or 0:.1f} min")

    if fail:
        log(f"[FAIL] {name} 有 {len(fail)} 段不完整: {fail[:5]}")
        return False

    # 拼接（顺序 cat，避免 shell 通配顺序问题）
    log(f"[cat] 拼接 {nseg} 段 → {name}")
    with open(dst, "wb") as fo:
        for p in parts:
            with open(p, "rb") as fi:
                while True:
                    b = fi.read(8 << 20)
                    if not b:
                        break
                    fo.write(b)
            os.remove(p)

    ok, why = safetensors_ok(dst, want)
    dt = time.time() - t0
    if ok:
        log(f"[ok] {name} {want:,} B  {dt/60:.1f} min  ({why})")
        return True
    log(f"[FAIL] {name} 拼接后结构不符: {why}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--list", required=True, help="每行: <文件名> <字节数>")
    ap.add_argument("--conc", type=int, default=32)
    ap.add_argument("--seg-mb", type=int, default=32)
    ap.add_argument("--only", default="", help="只下某个 shard（调试）")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    host = probe_hosts()
    if not host:
        log("[FATAL] 所有镜像不可达（同命令双域名已对比过）")
        sys.exit(2)
    log(f"[host] 选定 {host}")

    # 小文件
    for fn in SMALL:
        dst = os.path.join(a.out, fn)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            continue
        if curl(f"https://{host}/{REPO}/resolve/main/{fn}", dst):
            log(f"[small] {fn} {os.path.getsize(dst):,} B")
        else:
            log(f"[small][skip] {fn} 取不到（可选文件）")
            if os.path.exists(dst):
                os.remove(dst)

    shards = []
    with open(a.list, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            shards.append((parts[0], int(parts[1])))
    if a.only:
        shards = [s for s in shards if a.only in s[0]]

    total = sum(s[1] for s in shards)
    log(f"[plan] {len(shards)} 片 / {total:,} B ({total/1e9:.2f} GB)")

    t_start = time.time()
    bad = []
    for idx, (name, want) in enumerate(shards, 1):
        log(f"=== [{idx}/{len(shards)}] {name} ===")
        if not fetch_shard(host, name, want, a.out, a.seg_mb, a.conc, None):
            bad.append(name)
            break  # 一片失败就停，避免继续烧时间
    dt = time.time() - t_start
    if bad:
        log(f"[FAIL] 中断于 {bad}，已用时 {dt/60:.1f} min")
        sys.exit(3)

    # 总校验
    files = sorted(x for x in os.listdir(a.out) if x.endswith(".safetensors"))
    sizes = {f: os.path.getsize(os.path.join(a.out, f)) for f in files}
    tot = sum(sizes.values())
    log(f"[done] {len(files)} 片 / {tot:,} B / 用时 {dt/60:.1f} min "
        f"({tot/dt/1e6:.1f} MB/s 均速)")
    idxp = os.path.join(a.out, "model.safetensors.index.json")
    if os.path.exists(idxp):
        wm = json.load(open(idxp, encoding="utf-8"))["weight_map"]
        log(f"[verify] index 张量数 = {len(wm)}（期望 1199）")
    if len(files) != len(shards):
        log(f"[FAIL] 片数 {len(files)} != {len(shards)}")
        sys.exit(4)
    log("[PASS] 全部片到位")


if __name__ == "__main__":
    main()
