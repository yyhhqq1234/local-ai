import io
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"

# 文档引用重定向表
REPL = [
    ("`PLAN-OXCODER-POSTTRAIN.md`", "`docs/plans.md`"),
    ("`PLAN-KITTYREV-27B-GEN3.md`", "`docs/plans.md`"),
    ("`PLANS.md`", "`docs/plans.md`"),
    ("docs/01-architecture.md", "docs/architecture.md"),
    ("docs/02-local-model-adapter.md", "docs/architecture.md"),
    ("docs/05-optimization-log.md", "docs/architecture.md"),
    ("docs/03-posttraining.md", "docs/training.md"),
    ("docs/06-posttraining-feasibility.md", "docs/training.md"),
    ("docs/04-drce-linkage.md", "docs/operations.md"),
    # 引擎/模型新位置（禁删清单与目录速查）
    ("| `ninfer-27b-kv-stream-3arch-20261019/`", "| `engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019/`"),
    ("| `ninfer-csunx/`", "| `engines/ninfer-9b/ninfer-csunx/`"),
    ("ninfer-csunx/               引擎（不入库）", "engines/                    推理引擎（ninfer-9b / ninfer-27b / llama-cpp）"),
    ("ninfer-27b-*/               模型权重（22G，不入库）", "models/                     已交付模型（9b/gguf 与 9b/ninfer）"),
    ("cd D:\\BaiduNetdiskDownload\\Local-AI\\engines\\ninfer-9b\\ninfer-csunx", "cd D:\\BaiduNetdiskDownload\\Local-AI\\engines\\ninfer-9b\\ninfer-csunx"),
]

changed = []
for f in ("AGENTS.md", "README.md", "CLAUDE.md"):
    p = os.path.join(ROOT, f)
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding="utf-8").read()
    t = s
    for a, b in REPL:
        t = t.replace(a, b)
    if t != s:
        io.open(p, "w", encoding="utf-8").write(t)
        changed.append(f)

# README 顶部补一段目录结构（只加一次）
p = os.path.join(ROOT, "README.md")
s = io.open(p, encoding="utf-8").read()
if "## 目录结构（2026-11-12）" not in s:
    block = """## 目录结构（2026-11-12）

```text
AGENTS.md CLAUDE.md README.md TASKPOINT.md     入口与断点（根下只留这 4 个 md）
docs/            architecture.md · training.md · operations.md · plans.md
engines/         ninfer-27b/ · ninfer-9b/ · llama-cpp/  （推理引擎，按引擎分子目录）
models/          9b/gguf/（Q5_K_M-im · Q6_K · Q8_0）· 9b/ninfer/（交付版 .ninfer）
plugins/         dsh-local-ai（本地AI，DSH 适配器）
train/           后训练工作区（结构与产物落位保持不变）
_work/           过程产物：ninfer-9b 实验脚本 · _research · _archive（md 归档 zip）· session-audit
_tools/          构建工具链（cmake / ninfer-build）
```

"""
    io.open(p, "w", encoding="utf-8").write(block + s)
    changed.append("README.md(+结构)")

print("changed:", changed)
