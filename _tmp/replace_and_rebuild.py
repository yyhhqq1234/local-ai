# -*- coding: utf-8 -*-
"""替换 nsfw.jsonl 为 v3 全量，删除旧迭代，重建下游"""
import os, shutil, subprocess, sys, json

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")
SCRIPTS = os.path.join(TRAIN, "scripts")

def log(msg):
    print(f"  {msg}", flush=True)

# 1) 备份 v1
log("[1] 备份 nsfw.jsonl → nsfw-v1-backup.jsonl")
shutil.copy2(os.path.join(DATA, "nsfw.jsonl"), os.path.join(DATA, "nsfw-v1-backup.jsonl"))

# 2) 用 nsfw-v3.jsonl 替换 nsfw.jsonl
log("[2] nsfw-v3.jsonl → nsfw.jsonl")
shutil.copy2(os.path.join(DATA, "nsfw-v3.jsonl"), os.path.join(DATA, "nsfw.jsonl"))

# 3) 删除旧迭代
log("[3] 删除旧迭代")
for old in ["nsfw-train-v2.jsonl", "nsfw-train-v3.jsonl", "nsfw-train-v4.jsonl",
            "nsfw-train-v5.jsonl", "nsfw-train-v6.jsonl"]:
    fp = os.path.join(DATA, old)
    if os.path.isfile(fp):
        size = os.path.getsize(fp)
        os.remove(fp)
        log(f"  删除 {old} ({size:,} bytes)")
    else:
        log(f"  [skip] {old}")

# 4) 删除旧下游（将被重建）
log("[4] 删除旧下游产物")
for old in ["final-nsfw.jsonl", "final-joint.jsonl", "final-re.jsonl",
            "final-manifest.json", "mix-nsfw.jsonl", "mix-joint.jsonl"]:
    fp = os.path.join(DATA, old)
    if os.path.isfile(fp):
        size = os.path.getsize(fp)
        os.remove(fp)
        log(f"  删除 {old} ({size:,} bytes)")
    else:
        log(f"  [skip] {old}")

# 5) 重跑 build_final.py
log("[5] 重跑 build_final.py")
result = subprocess.run(
    [sys.executable, os.path.join(SCRIPTS, "build_final.py"),
     "--re-weight", "0.6", "--replay", "0.15"],
    capture_output=True, text=True, cwd=TRAIN
)
if result.returncode != 0:
    log(f"  [ERROR] build_final.py:\n{result.stderr[-2000:]}")
    sys.exit(1)
log(f"  build_final.py 完成")

# 6) 重跑 build_mix.py（两个 stage）
log("[6] 重跑 build_mix.py")
for stage, out in [("nsfw", "mix-nsfw.jsonl"), ("joint", "mix-joint.jsonl")]:
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "build_mix.py"),
         "--stage", stage, "--out", os.path.join(DATA, out)],
        capture_output=True, text=True, cwd=TRAIN
    )
    if result.returncode != 0:
        log(f"  [ERROR] build_mix.py --stage {stage}:\n{result.stderr[-2000:]}")
        sys.exit(1)
    log(f"  build_mix.py --stage {stage} 完成")

# 7) 验证
log("[7] 验证下游行数")
for name in ["nsfw.jsonl", "final-nsfw.jsonl", "final-joint.jsonl",
             "mix-nsfw.jsonl", "mix-joint.jsonl"]:
    fp = os.path.join(DATA, name)
    if os.path.isfile(fp):
        n = sum(1 for _ in open(fp, "rb"))
        size = os.path.getsize(fp)
        log(f"  {name}: {n:,} rows, {size:,} bytes")
    else:
        log(f"  [MISS] {name}")

log("[DONE]")
