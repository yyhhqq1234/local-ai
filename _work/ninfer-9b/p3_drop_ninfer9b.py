import io
import json
import os
import shutil

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
LIB = os.path.join(ROOT, "plugins", "dsh-local-ai", "lib", "index.js")
PATCH = os.path.join(ROOT, "plugins", "dsh-local-ai", "cordis.patch.yml")
OLDC = os.path.join(ROOT, "engines", "ninfer-9b", "ninfer-csunx", "config", "engine.json")
NEWC_DIR = os.path.join(ROOT, "engines", "llama-cpp", "config")
NEWC = os.path.join(NEWC_DIR, "engine.json")

# 1) 迁移插件参数目录到 engines/llama-cpp/config
os.makedirs(NEWC_DIR, exist_ok=True)
if os.path.exists(OLDC):
    d = json.load(io.open(OLDC, encoding="utf-8"))
    d["profile"] = "llama-cpp"
    d["modelFile"] = "D:/BaiduNetdiskDownload/Local-AI/models/9b/gguf/kittyrev9b-Q5_K_M-im.gguf"
    d["maxContext"] = 8192
    d["port"] = 8080
    json.dump(d, io.open(NEWC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("engine.json -> engines/llama-cpp/config")

# 2) 插件 patch：engineDir 指向 llama-cpp
s = io.open(PATCH, encoding="utf-8").read()
s = s.replace("engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-9b/ninfer-csunx'",
              "engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/llama-cpp'")
io.open(PATCH, "w", encoding="utf-8").write(s)

# 3) lib：默认 engineDir + 删除 build-9b 档 + csunx-27b 的 9B modelDirs
L = io.open(LIB, encoding="utf-8").read()
L = L.replace("engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-9b/ninfer-csunx'",
              "engineDir: 'D:/BaiduNetdiskDownload/Local-AI/engines/llama-cpp'")

# 删除整段 build-9b 配置
start = L.find("  'build-9b': {")
if start != -1:
    end = L.find("\n  },", start)
    if end != -1:
        L = L[:start] + L[end + len("\n  },"):]
        print("removed build-9b profile")

# csunx-27b 的 modelDirs 去掉 9B 那条
L = L.replace("      'D:/BaiduNetdiskDownload/Local-AI/engines/ninfer-9b/ninfer-csunx/model',\n", "")
io.open(LIB, "w", encoding="utf-8").write(L)
print("lib updated")
