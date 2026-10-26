#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""artifact_formats.py —— 统计 .ninfer v3 artifact 里的 format 分布、object 数、字节占比

用法: python artifact_formats.py <artifact 路径>
不依赖数值库（纯读容器元数据）。
"""
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("D:/BaiduNetdiskDownload/Local-AI/train/tools/ninfer-master")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    art = sys.argv[1]
    py = sys.executable
    out = subprocess.run(
        [py, "-m", "tools.artifact.inspect", art, "--objects", "--bindings", "--json"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        print("INSPECT_FAIL", out.stderr[:400])
        return 1
    d = json.loads(out.stdout)
    print("version", d.get("version"), "name", d.get("name"))
    print("top keys", list(d))

    objects = d.get("objects") or []
    print("objects", len(objects))
    if objects:
        print("object[0] keys", list(objects[0]))
        print("sample", json.dumps(objects[0], ensure_ascii=False)[:300])

    fmt = Counter()
    nbytes = defaultdict(int)
    for o in objects:
        f = o.get("format") or o.get("codec") or "?"
        fmt[f] += 1
        for k in ("nbytes", "bytes", "size", "byte_length"):
            if isinstance(o.get(k), int):
                nbytes[f] += o[k]
                break
    print("\n=== formats ===")
    for f, n in fmt.most_common():
        print(f"{f:34s} objects={n:5d}  bytes={nbytes.get(f, 0):>15,}")

    files = d.get("files") or d.get("physical_files") or []
    if files:
        print("\n=== files ===")
        for f in files[:6]:
            print(json.dumps(f, ensure_ascii=False)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
