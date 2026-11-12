import io
import json
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
GOOD = "D:/BaiduNetdiskDownload/Local-AI/_work/ninfer-9b/gguf/kittyrev9b-Q5_K_M-im.gguf"

# 1) 插件参数
cfg = os.path.join(ROOT, "ninfer-csunx", "config", "engine.json")
d = json.load(io.open(cfg, encoding="utf-8"))
d["profile"] = "llama-cpp"
d["modelFile"] = GOOD
d["maxContext"] = 8192
d["port"] = 8080
d["reasoningEffort"] = "none"
json.dump(d, io.open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("engine.json fixed:", d["maxContext"], d["port"])

# 2) 适配器里的默认模型路径（修正 infer-9b → ninfer-9b）
lib = os.path.join(ROOT, "plugins", "dsh-local-ai", "lib", "index.js")
s = io.open(lib, encoding="utf-8").read()
s2 = s.replace("_work/infer-9b/gguf/kittyrev9b-Q5_K_M-im.gguf", "_work/ninfer-9b/gguf/kittyrev9b-Q5_K_M-im.gguf")
s2 = s2.replace("_work\\infer-9b\\gguf", "_work\\ninfer-9b\\gguf")
if s2 != s:
    io.open(lib, "w", encoding="utf-8").write(s2)
print("adapter path fixed:", "_work/infer-9b" not in s2)

# 3) 校验文件真实存在
print("model exists:", os.path.isfile(GOOD.replace("/", "\\")))
