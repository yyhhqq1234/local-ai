import io
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
files = ["AGENTS.md", "README.md", "CLAUDE.md"]
repl = [
    ("plugins/dsh-ninfer-local", "plugins/dsh-local-ai"),
    ("`plugins/dsh-ninfer-local/", "`plugins/dsh-local-ai/"),
]
for f in files:
    p = os.path.join(ROOT, f)
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding="utf-8").read()
    t = s
    for a, b in repl:
        t = t.replace(a, b)
    if t != s:
        io.open(p, "w", encoding="utf-8").write(t)
        print("updated", f)

# README: 在适配器段落追加 llama.cpp 主用说明（只加一次）
p = os.path.join(ROOT, "README.md")
s = io.open(p, encoding="utf-8").read()
marker = "llama.cpp"
if marker not in s:
    add = (
        "\n## 本地模型服务（2026-11-12 起）\n\n"
        "```text\n"
        "主用：llama.cpp CUDA（llama-server，GPU 全量 offload，端口 8080）\n"
        "      模型：_work/ninfer-9b/gguf/kittyrev9b-Q5_K_M-im.gguf（6.19 GB，Q5_K_M + imatrix）\n"
        "      启动：_work/ninfer-9b/p3_llama_serve.bat\n"
        "      实测：decode 中位 ~70 tok/s，17/17 回归通过，PPL 3.708（Q8_0 基线 3.692，+0.43%）\n"
        "适配器：plugins/dsh-local-ai（本地AI），profile=llama-cpp 指向 127.0.0.1:8080/v1\n"
        "备用：NInfer 引擎（build-9b，35 tok/s，保留 27B 路线与对照）\n"
        "```\n"
    )
    io.open(p, "w", encoding="utf-8").write(s + add)
    print("README appended")
