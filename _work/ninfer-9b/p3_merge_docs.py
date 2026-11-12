import io
import os
import shutil
import zipfile

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"


def read(p):
    return io.open(p, encoding="utf-8", errors="ignore").read()


def merge(parts, out_path, title):
    buf = ["# " + title + "\n", "> 合并自：" + "、".join(os.path.basename(p) for p in parts) + "\n"]
    for p in parts:
        if not os.path.exists(p):
            continue
        buf.append("\n---\n\n## " + os.path.basename(p) + "\n")
        buf.append(read(p))
    io.open(out_path, "w", encoding="utf-8").write("\n".join(buf))
    for p in parts:
        if os.path.exists(p) and os.path.abspath(p) != os.path.abspath(out_path):
            os.remove(p)
    print("merged ->", os.path.basename(out_path), "from", len(parts))


D = os.path.join(ROOT, "docs")
os.makedirs(D, exist_ok=True)

# docs：6 → 3（+ plans）
merge([os.path.join(D, "01-architecture.md"),
       os.path.join(D, "02-local-model-adapter.md"),
       os.path.join(D, "05-optimization-log.md")],
      os.path.join(D, "architecture.md"), "架构 · 适配器 · 优化日志")

merge([os.path.join(D, "03-posttraining.md"),
       os.path.join(D, "06-posttraining-feasibility.md")],
      os.path.join(D, "training.md"), "后训练")

if os.path.exists(os.path.join(D, "04-drce-linkage.md")):
    os.rename(os.path.join(D, "04-drce-linkage.md"), os.path.join(D, "operations.md"))
    s = read(os.path.join(D, "operations.md"))
    io.open(os.path.join(D, "operations.md"), "w", encoding="utf-8").write("# 运维与联动\n\n" + s)

# 根目录三份计划 → docs/plans.md
merge([os.path.join(ROOT, "PLANS.md"),
       os.path.join(ROOT, "PLAN-OXCODER-POSTTRAIN.md"),
       os.path.join(ROOT, "PLAN-KITTYREV-27B-GEN3.md")],
      os.path.join(D, "plans.md"), "计划（两条训练线）")

# _work 下自有笔记归档成 zip
def zip_md(src_dir, zip_path):
    if not os.path.isdir(src_dir):
        return 0
    files = []
    for dirpath, _, names in os.walk(src_dir):
        for n in names:
            if n.lower().endswith(".md"):
                files.append(os.path.join(dirpath, n))
    if not files:
        return 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.relpath(f, src_dir))
            os.remove(f)
    print("zipped", len(files), "md ->", os.path.basename(zip_path))
    return len(files)


A = os.path.join(ROOT, "_work", "_archive")
os.makedirs(A, exist_ok=True)
n1 = zip_md(os.path.join(ROOT, "_work", "_research"), os.path.join(A, "research-notes-md.zip"))
n2 = zip_md(os.path.join(ROOT, "_work", "session-audit"), os.path.join(A, "session-audit-md.zip"))

# _work/ninfer-9b：保留 TASKPOINT.md，其余 md 归档
nb = os.path.join(ROOT, "_work", "ninfer-9b")
keep = {"TASKPOINT.md"}
if os.path.isdir(nb):
    files = [os.path.join(nb, f) for f in os.listdir(nb)
             if f.lower().endswith(".md") and f not in keep]
    if files:
        with zipfile.ZipFile(os.path.join(A, "ninfer-9b-notes-md.zip"), "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, os.path.basename(f))
                os.remove(f)
        print("zipped", len(files), "md -> ninfer-9b-notes-md.zip")

print("done", n1, n2)
