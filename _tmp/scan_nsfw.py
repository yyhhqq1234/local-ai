# -*- coding: utf-8 -*-
"""扫描 NSFW 小说目录，统计文件数/字数，对比 index.jsonl 覆盖情况"""
import os, json, sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
SRC = os.path.join(BASE, "user-temp", "NSFW小说")

files = []
total_chars = 0
for root, dirs, fnames in os.walk(SRC):
    for fn in fnames:
        if fn.endswith(".txt"):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, SRC)
            sz = os.path.getsize(fp)
            # rough char count (bytes / 3 for CJK)
            files.append((rel, sz))
            total_chars += sz // 3  # approx

print(f"[FILES] {len(files)} txt files found")
print(f"[CHARS] approx total chars: {total_chars:,}")
print()

# Compare with index.jsonl
idx_path = os.path.join(BASE, "train", "data", "nsfw-index", "index.jsonl")
if os.path.isfile(idx_path):
    idx_files = []
    with open(idx_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                idx_files.append(r["rel"])
    print(f"[INDEX] {len(idx_files)} files in index.jsonl")
    missing = [f for f in files if f[0] not in set(idx_files)]
    extra = [i for i in idx_files if i not in set(f[0] for f in files)]
    print(f"[MISSING from index] {len(missing)}")
    for m in missing[:20]:
        print(f"  {m[0]}  ({m[1]:,} bytes)")
    print(f"[EXTRA in index] {len(extra)}")
    for e in extra[:10]:
        print(f"  {e}")
else:
    print("[INDEX] index.jsonl not found at expected path")
    # search for it
    for d in ("train/data/nsfw-index/", "train/data/"):
        p = os.path.join(BASE, d)
        if os.path.isdir(p):
            print(f"  contents of {p}: {os.listdir(p)}")

# Also check the subdirectory structure
print("\n[DIR STRUCTURE]")
for root, dirs, fnames in os.walk(SRC):
    depth = os.path.relpath(root, SRC).count(os.sep)
    if depth <= 2:
        n = len([f for f in fnames if f.endswith(".txt")])
        if n:
            print(f"  depth={depth} dir={root[len(SRC):]!r}  txt={n}")
