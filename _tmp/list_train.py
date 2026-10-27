# -*- coding: utf-8 -*-
"""列出 train/data/ 下所有文件（含子目录），标注新旧版本"""
import os, sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")

print("=== train/ root ===")
for fn in sorted(os.listdir(TRAIN)):
    fp = os.path.join(TRAIN, fn)
    if os.path.isfile(fp):
        sz = os.path.getsize(fp)
        print(f"  FILE  {sz:>12,}  {fn}")
    else:
        print(f"  DIR   {'':>12}  {fn}/")

print("\n=== train/data/ ===")
for fn in sorted(os.listdir(DATA)):
    fp = os.path.join(DATA, fn)
    if os.path.isfile(fp):
        sz = os.path.getsize(fp)
        print(f"  FILE  {sz:>12,}  {fn}")
    else:
        # count files inside
        n = 0
        for root, dirs, files in os.walk(fp):
            n += len([f for f in files if not f.startswith('.')])
        print(f"  DIR   {n:>10} files  {fn}/")

print("\n=== train/scripts/ ===")
scripts = os.path.join(TRAIN, "scripts")
if os.path.isdir(scripts):
    for fn in sorted(os.listdir(scripts)):
        fp = os.path.join(scripts, fn)
        if os.path.isfile(fp):
            sz = os.path.getsize(fp)
            print(f"  FILE  {sz:>12,}  {fn}")
