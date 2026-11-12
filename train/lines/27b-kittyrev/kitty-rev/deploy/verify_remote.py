#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_remote.py —— 远端已传文件完整性抽样校验（比 size 更强的判据）

背景：本机重启/中断多次，远端存在"半截文件"和"曾被 wb 截断后重写"的文件。
      逐字节 md5 要双向各读 52GB（太慢），这里做**抽样块比对**：
      每个文件取 4 个 64KB 块（头 / 1/3 / 2/3 / 尾），远端 dd 出来与本机同偏移比对。
      半截文件只比对落在已传范围内的块 → 验证 append 续传的起点是否对齐。

判定：
  OK       远端 size == 本地 size 且 4 块一致
  PARTIAL  远端 size < 本地 size 且所有可校验块一致  → 可安全续传
  BAD      任何块不一致 / 远端 size > 本地 size    → 删除重传

用法：
  python verify_remote.py --dir base/Qwen3.8-27B --remote /root/autodl-tmp/kitty-rev/base/Qwen3.8-27B [--fix]
  --fix   自动删除 BAD 文件（不删 PARTIAL）
"""
import argparse
import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remote as R
import up_par

BLK = 65536


def local_block(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def remote_block(c, rpath, off, n):
    """dd 出远端一段，base64 回传后解码（避免二进制经 shell 损坏）"""
    cmd = f"dd if='{rpath}' bs=1 skip={off} count={n} 2>/dev/null | base64 -w0"
    _, out = R.run(c, cmd, timeout=120, quiet=True)
    s = "".join((out or "").split())
    if not s:
        return b""
    try:
        return base64.b64decode(s)
    except Exception:
        return b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--remote", required=True)
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    a.remote = up_par.fix_remote(a.remote)

    files = [f for f in sorted(os.listdir(a.dir)) if os.path.isfile(os.path.join(a.dir, f))]
    c = R.connect()
    try:
        verdict = {}
        for f in files:
            lp = os.path.join(a.dir, f)
            rp = f"{a.remote}/{f}"
            lsz = os.path.getsize(lp)
            _, out = R.run(c, f"stat -c %s '{rp}' 2>/dev/null || echo -1", timeout=60, quiet=True)
            try:
                rsz = int((out or "-1").strip().splitlines()[-1])
            except Exception:
                rsz = -1
            if rsz > lsz:
                verdict[f] = ("BAD", f"远端更大 {rsz}>{lsz}")
                continue
            if rsz <= 0:
                verdict[f] = ("MISSING", "远端不存在")
                continue
            span = min(rsz, lsz)
            offs = [0, max(0, span // 3), max(0, span * 2 // 3), max(0, span - BLK)]
            bad = []
            for off in offs:
                n = min(BLK, span - off)
                if n <= 0:
                    continue
                lb = local_block(lp, off, n)
                rb = remote_block(c, rp, off, n)
                if lb != rb:
                    bad.append(off)
            state = "OK" if rsz == lsz and not bad else ("PARTIAL" if not bad else "BAD")
            note = "" if not bad else f"块不一致@{bad}"
            verdict[f] = (state, note)
            print(f"  {state:8s} {f}  远端 {rsz/1e9:.3f}GB / 本地 {lsz/1e9:.3f}GB {note}", flush=True)
    finally:
        try:
            c.close()
        except Exception:
            pass

    bad = [f for f, (s, _) in verdict.items() if s == "BAD"]
    missing = [f for f, (s, _) in verdict.items() if s == "MISSING"]
    part = [f for f, (s, _) in verdict.items() if s == "PARTIAL"]
    ok = [f for f, (s, _) in verdict.items() if s == "OK"]
    print(f"\n[summary] OK={len(ok)} PARTIAL={len(part)} BAD={len(bad)} MISSING={len(missing)}")
    if bad:
        print("BAD: " + " ".join(bad))
    if missing:
        print("MISSING: " + " ".join(missing))
    if a.fix and (bad or missing):
        c2 = R.connect()
        try:
            for f in bad:
                R.run(c2, f"rm -f '{a.remote}/{f}'", timeout=60)
                print(f"  [rm] {f}")
        finally:
            try:
                c2.close()
            except Exception:
                pass
        print("[fix] 已删除 BAD（下次 --resume 会整片重传）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
