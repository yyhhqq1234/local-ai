import io
import json
import os
import re

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
SL = "/"

REPL = [
    # 引擎位置
    ("D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx", "D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-9b/ninfer-csunx"),
    ("D:/BaiduNetdiskDownload/Local-AI/ninfer-27b-kv-stream-3arch-20261019",
     "D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019"),
    # 模型位置
    ("D:/BaiduNetdiskDownload/Local-AI/_work/ninfer-9b/gguf", "D:/BaiduNetdiskDownload/Local-AI/models/9b/gguf"),
    ("D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out", "D:/BaiduNetdiskDownload/Local-AI/models/9b/ninfer"),
    # llama.cpp 引擎
    ("D:/BaiduNetdiskDownload/Local-AI/_work/ninfer-9b/llama-bin", "D:/BaiduNetdiskDownload/Local-AI/engines/llama-cpp/llama-bin"),
]

TARGETS = [
    "plugins/dsh-local-ai/lib/index.js",
    "plugins/dsh-local-ai/src/adapter.ts",
    "plugins/dsh-local-ai/cordis.patch.yml",
    "engines/ninfer-9b/ninfer-csunx/config/engine.json",
    "engines/llama-cpp/serve.bat",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
]

changed = []
for rel in TARGETS:
    p = os.path.join(ROOT, rel.replace("/", "\\"))
    if not os.path.exists(p):
        continue
    s = io.open(p, encoding="utf-8", errors="ignore").read()
    t = s
    for a, b in REPL:
        t = t.replace(a, b)
        # 反斜杠形式（bat / ps1 常见）
        t = t.replace(a.replace("/", "\\"), b.replace("/", "\\"))
    if t != s:
        io.open(p, "w", encoding="utf-8").write(t)
        changed.append(rel)

# engine.json：确认 modelFile / port / ctx
cfg = os.path.join(ROOT, "engines", "ninfer-9b", "ninfer-csunx", "config", "engine.json")
if os.path.exists(cfg):
    d = json.load(io.open(cfg, encoding="utf-8"))
    d["modelFile"] = "D:/BaiduNetdiskDownload/Local-AI/models/9b/gguf/kittyrev9b-Q5_K_M-im.gguf"
    d["maxContext"] = 8192
    d["port"] = 8080
    json.dump(d, io.open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(json.dumps({"changed": changed}, ensure_ascii=False))
