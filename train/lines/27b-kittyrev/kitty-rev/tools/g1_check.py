#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""g1_check.py —— base 18 片完整性硬校验（逐片等号，不看总量）

判据（任一不过 exit!=0）：
  1) 18 个 model-*-of-00018.safetensors 都在
  2) 每片 size == shards.txt 权威值
  3) 总和 == 55,563,006,216
  4) index.json weight_map 张量数 == 1199
  5) 每片结构式 8 + header_len + max(data_offsets) == filesize
"""
import argparse
import json
import os
import struct
import sys

EXPECT_TOTAL = 55563006216
EXPECT_TENSORS = 1199


def struct_ok(path):
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as f:
            (n,) = struct.unpack("<Q", f.read(8))
            if not (0 < n < 200 << 20):
                return False, f"header_len={n} 异常"
            hdr = json.loads(f.read(n).decode("utf-8"))
        hdr.pop("__metadata__", None)
        mx = max(v["data_offsets"][1] for v in hdr.values())
        if 8 + n + mx != sz:
            return False, f"struct {8+n+mx} != {sz}"
        return True, f"{len(hdr)} tensors"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--list", required=True)
    a = ap.parse_args()
    want = []
    for line in open(a.list, encoding="utf-8"):
        line = line.strip()
        if line:
            p = line.split()
            want.append((p[0], int(p[1])))
    print(f"[G1] 清单 {len(want)} 片，权威合计 {sum(w for _, w in want):,} B")
    bad = []
    tot = 0
    for name, w in want:
        p = os.path.join(a.base, name)
        if not os.path.exists(p):
            bad.append(f"{name}: 缺失")
            continue
        got = os.path.getsize(p)
        tot += got
        if got != w:
            bad.append(f"{name}: {got:,} != {w:,}")
            continue
        ok, why = struct_ok(p)
        print(f"  {'OK  ' if ok else 'BAD '} {name}  {got:>13,}  {why}")
        if not ok:
            bad.append(f"{name}: 结构 {why}")
    print(f"[G1] 实际合计 {tot:,} B（期望 {EXPECT_TOTAL:,}）差异 {tot-EXPECT_TOTAL:+,}")
    if tot != EXPECT_TOTAL:
        bad.append(f"合计不符 {tot}")
    idxp = os.path.join(a.base, "model.safetensors.index.json")
    if os.path.exists(idxp):
        wm = json.load(open(idxp, encoding="utf-8"))["weight_map"]
        print(f"[G1] index 张量数 {len(wm)}（期望 {EXPECT_TENSORS}）")
        if len(wm) != EXPECT_TENSORS:
            bad.append(f"index 张量数 {len(wm)} != {EXPECT_TENSORS}")
    else:
        bad.append("缺 index.json")
    if bad:
        print(f"[G1] FAIL {len(bad)} 项")
        for b in bad:
            print("   ✗", b)
        return 1
    print("[G1] PASS 18 片 / 结构自洽 / 合计与 index 均匹配")
    return 0


if __name__ == "__main__":
    sys.exit(main())
