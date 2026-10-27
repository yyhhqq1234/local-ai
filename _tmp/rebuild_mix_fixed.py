# -*- coding: utf-8 -*-
"""用修复后的 build_mix.py 重建 mix-nsfw / mix-joint，验证 meta 透传"""
import os, subprocess, sys, json, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")
SCRIPTS = os.path.join(TRAIN, "scripts")

for stage, out in [("nsfw", "mix-nsfw.jsonl"), ("joint", "mix-joint.jsonl")]:
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "build_mix.py"),
         "--stage", stage, "--out", os.path.join(DATA, out)],
        capture_output=True, text=True, cwd=TRAIN
    )
    if result.returncode != 0:
        print(f"[ERROR] --stage {stage}:\n{result.stderr[-2000:]}", flush=True)
        sys.exit(1)
    print(f"[OK] --stage {stage} → {out}", flush=True)

# 验证 meta 透传
fp = os.path.join(DATA, "mix-nsfw.jsonl")
stype = collections.Counter()
level = collections.Counter()
minor = collections.Counter()
n = 0
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
            m = o.get("meta", {})
            stype[m.get("stype", "-")] += 1
            level[m.get("level", "-")] += 1
            minor[m.get("minor_flag", None)] += 1
        except Exception:
            pass

print(f"\nmix-nsfw.jsonl 行数: {n}")
print(f"  stype 分布: {dict(stype)}")
print(f"  level 分布: {dict(level)}")
print(f"  minor_flag: {dict(minor)}")
print("[DONE]")
