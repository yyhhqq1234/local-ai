"""结项文档收敛：过时过程日志归档成 zip 后删除；核心方法论文档保留；过时结论并入 HISTORY。"""
import io
import os
import shutil
import zipfile

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(ROOT, "train")
ARCH = os.path.join(TRAIN, "logs", "_archive")
os.makedirs(ARCH, exist_ok=True)

# ---- 1. kitty-rev/logs 下的逐轮日志（v4/v5/v6/v7 + 临时自测） → 归档 ----
KR = os.path.join(TRAIN, "lines", "27b-kittyrev", "kitty-rev", "logs")
zip_targets = []

for sub in ("v4", "v5", "v6", "v7", "_v4selftest"):
    d = os.path.join(KR, sub)
    if os.path.isdir(d):
        zip_targets.append(d)

def zip_dir(src, zip_path):
    files = []
    for dp, _, names in os.walk(src):
        for n in names:
            if n.lower().endswith(".md"):
                files.append(os.path.join(dp, n))
    if not files:
        return 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.relpath(f, src))
    shutil.rmtree(src, ignore_errors=True)
    return len(files)

total = 0
for d in zip_targets:
    n = zip_dir(d, os.path.join(ARCH, "kittyrev-logs-%s.zip" % os.path.basename(d)))
    total += n
    print("archived", os.path.basename(d), n, "md")
print("kittyrev logs 归档:", total)

# ---- 2. train/logs 下的监控与逐轮报告 → 归档 ----
LG = os.path.join(TRAIN, "logs")
keep_logs = {"z-final-report.md"}  # 已并入 docs/plans.md，保留原文件到归档即可
log_md = [f for f in os.listdir(LG) if f.endswith(".md")]
if log_md:
    with zipfile.ZipFile(os.path.join(ARCH, "train-logs.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in log_md:
            z.write(os.path.join(LG, f), f)
            os.remove(os.path.join(LG, f))
    print("train/logs 归档:", len(log_md))

# ---- 3. train 根：过时结论/过程报告 → 归档；方法论保留 ----
KEEP_TRAIN = {
    "README.md", "PITFALLS.md", "EVAL-PROTOCOL.md", "PREFLIGHT.md",
    "ANTI-MEMORIZATION.md", "TRAINING-LINEAGE.md",
}
train_md = [f for f in os.listdir(TRAIN) if f.endswith(".md") and f not in KEEP_TRAIN]
if train_md:
    with zipfile.ZipFile(os.path.join(ARCH, "train-root-obsolete.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for f in train_md:
            z.write(os.path.join(TRAIN, f), f)
            os.remove(os.path.join(TRAIN, f))
    print("train 根过时归档:", len(train_md), "→", ARCH)

# ---- 4. 零散过程 md（自测/临时）→ 直接删 ----
misc_del = [
    os.path.join(KR, "tmp"),
    os.path.join(TRAIN, "lines", "27b-kittyrev", "kitty-rev", "tmp"),
]
for d in misc_del:
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        print("removed", d)

print("done")
