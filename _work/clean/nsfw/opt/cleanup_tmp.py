# -*- coding: utf-8 -*-
"""cleanup_tmp.py — 删除本轮临时文件（探针脚本与写权限测试文件）。"""
import os

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\clean\nsfw\opt"
OPT = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\data\nsfw-gated\cleaned\opt"
targets = [
    os.path.join(OPT, "_wtest.txt"),
    os.path.join(OPT, "_wtest2.txt"),
    os.path.join(BASE, "_wtest.txt"),
    os.path.join(BASE, "_wtest2.txt"),
    os.path.join(BASE, "_probe_v4.py"),
    os.path.join(BASE, "_probe_v4b.py"),
    os.path.join(BASE, "_probe_v4c.py"),
    os.path.join(BASE, "_probe_v4d.py"),
    os.path.join(BASE, "_probe_v4e.py"),
    os.path.join(BASE, "_probe_v4f.py"),
    os.path.join(BASE, "_probe_v4g.py"),
    os.path.join(BASE, "_probe_v4h.py"),
    os.path.join(BASE, "_probe_v4i.py"),
    os.path.join(BASE, "_probe_v4j.py"),
    os.path.join(BASE, "_probe_v4k.py"),
]
for p in targets:
    try:
        os.remove(p)
        print("removed", os.path.basename(p))
    except FileNotFoundError:
        pass
    except Exception as e:
        print("ERR", p, e)
print("done")
