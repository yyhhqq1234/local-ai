#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_aria2_list.py —— 从 hf-mirror API 生成 aria2 输入清单（多连接下载 27B 基座）

用法：python3 gen_aria2_list.py --repo Qwen/Qwen3.8-27B --out /root/autodl-tmp/base.aria2.txt --dest /root/autodl-tmp/kitty-rev/base/Qwen3.8-27B
"""
import argparse
import json
import os
import subprocess

MIRROR = "https://hf-mirror.com"
ALLOW = (".json", ".safetensors", ".jinja", ".txt", ".model")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="Qwen/Qwen3.8-27B")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    url = f"{MIRROR}/api/models/{a.repo}"
    raw = subprocess.run(["curl", "-sS", "-m", "60", url], capture_output=True, check=True).stdout
    d = json.loads(raw.decode("utf-8", "replace"))
    files = [f["rfilename"] for f in d.get("siblings", []) if f["rfilename"].endswith(ALLOW)]
    os.makedirs(a.dest, exist_ok=True)
    total = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for name in files:
            f.write(f"{MIRROR}/{a.repo}/resolve/main/{name}\n")
            f.write(f"  dir={a.dest}\n")
            f.write(f"  out={name}\n")
    print(f"[list] {len(files)} files → {a.out}")
    for n in files[:6]:
        print("   ", n)


if __name__ == "__main__":
    main()
