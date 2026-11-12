import io
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"

# AGENTS：27B 那行补充"模型已清空"
p = os.path.join(ROOT, "AGENTS.md")
s = io.open(p, encoding="utf-8").read()
s = s.replace(
    "| `engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019/` | **本地模型推理引擎**（23 GB：`launcher.py` · `engines/` · `gateway/` · `model/*.ninfer` · `profiles.json` · `mcp_server.py`） | 27B 推理与 DSH 接引擎的能力全部失效，需重新下载整套运行时 |",
    "| `engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019/` | 27B NInfer 运行时（约 2.8 GB；**其中 `model/*.ninfer` 已于 2026-11-12 清空**——现在只保留 llama.cpp 的 GGUF 模型） | 删掉运行时会失去 27B 的重启能力（模型需重新量化/下载） |")
if "只保留 llama.cpp 的 GGUF 模型" not in s:
    s = s.replace(
        "9B 推理引擎只保留 llama.cpp（engines/llama-cpp）；NInfer 仅保留 27B（engines/ninfer-27b）",
        "9B 推理引擎只保留 llama.cpp（engines/llama-cpp）；模型只有 llama.cpp 的 GGUF（models/9b/gguf 3 个档）\n"
        "NInfer 27B 运行时保留，但其 .ninfer 模型已删除（2026-11-12，释放 19.4 GB）")
io.open(p, "w", encoding="utf-8").write(s)

# README / CLAUDE
for f in ("README.md", "CLAUDE.md"):
    q = os.path.join(ROOT, f)
    if not os.path.exists(q):
        continue
    t = io.open(q, encoding="utf-8").read()
    t = t.replace("models/                     已交付模型（9b/gguf：Q5_K_M-im / Q6_K / Q8_0）",
                  "models/                     已交付模型（仅 llama.cpp GGUF：9b/gguf Q5_K_M-im / Q6_K / Q8_0）")
    t = t.replace("models/          9b/gguf/（Q5_K_M-im · Q6_K · Q8_0）",
                  "models/          9b/gguf/（Q5_K_M-im · Q6_K · Q8_0）— 只有 GGUF")
    io.open(q, "w", encoding="utf-8").write(t)

print("docs updated")
