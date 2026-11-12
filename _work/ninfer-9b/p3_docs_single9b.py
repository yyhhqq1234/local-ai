import io
import os
import re

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"

# --- AGENTS.md：禁删清单去掉已删的 9B 引擎行 ---
p = os.path.join(ROOT, "AGENTS.md")
s = io.open(p, encoding="utf-8").read()
lines = [l for l in s.split("\n") if "engines/ninfer-9b/ninfer-csunx" not in l]
s = "\n".join(lines)
# 目录速查/说明里补一句 9B 只用 llama.cpp
if "9B 推理引擎只保留 llama.cpp" not in s:
    s = s.replace("| `plugins/` | DSH 适配器（NInfer 接入层） |",
                  "| `plugins/` | DSH 适配器（NInfer / llama.cpp 接入层） |")
    s = s.replace("---\n\n## 3 关键路径",
                  "```text\n9B 推理引擎只保留 llama.cpp（engines/llama-cpp）；NInfer 仅保留 27B（engines/ninfer-27b）\n"
                  "已删：engines/ninfer-9b（1.89 GB）、models/9b/ninfer（17.38 GB 旧 .ninfer）、_tools/ninfer-build（3.03 GB）\n```\n\n---\n\n## 3 关键路径")
io.open(p, "w", encoding="utf-8").write(s)
print("AGENTS updated")

# --- README / CLAUDE：目录速查同步 ---
for f in ("README.md", "CLAUDE.md"):
    q = os.path.join(ROOT, f)
    if not os.path.exists(q):
        continue
    t = io.open(q, encoding="utf-8").read()
    t = t.replace("engines/                    推理引擎（ninfer-9b / ninfer-27b / llama-cpp）",
                  "engines/                    推理引擎（llama-cpp 用于 9B · ninfer-27b 用于 27B）")
    t = t.replace("engines/                    推理引擎（ninfer-9b / ninfer-27b / llama-cpp）",
                  "engines/                    推理引擎（llama-cpp 9B · ninfer-27b 27B）")
    t = t.replace("models/                     已交付模型（9b/gguf 与 9b/ninfer）",
                  "models/                     已交付模型（9b/gguf：Q5_K_M-im / Q6_K / Q8_0）")
    t = t.replace("cd D:\\BaiduNetdiskDownload\\Local-AI\\engines\\ninfer-9b\\ninfer-csunx ; .\\run-engine.ps1",
                  "cd D:\\BaiduNetdiskDownload\\Local-AI\\engines\\llama-cpp ; .\\serve.bat")
    io.open(q, "w", encoding="utf-8").write(t)
    print("updated", f)
