import json
import os

D = r"D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai"
OLD = "dsh-ninfer-local"
NEW = "dsh-local-ai"

# package.json
pkg_path = os.path.join(D, "package.json")
pkg = json.load(open(pkg_path, encoding="utf-8"))
pkg["name"] = "@dsh-external/" + NEW
pkg["description"] = "本地AI：本地模型后端（llama.cpp CUDA 主用 / NInfer 备用）+ 模型与参数管理"
json.dump(pkg, open(pkg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# cordis.patch.yml
cp = os.path.join(D, "cordis.patch.yml")
s = open(cp, encoding="utf-8").read().replace(OLD, NEW)
s = s.replace("本地模型后端", "本地AI 本地模型后端")
open(cp, "w", encoding="utf-8").write(s)

# lib files
for f in ("lib/index.js", "lib/client.js"):
    q = os.path.join(D, f)
    if not os.path.exists(q):
        continue
    t = open(q, encoding="utf-8").read()
    t = t.replace("@dsh-external/" + OLD, "@dsh-external/" + NEW)
    t = t.replace("/" + OLD + "/api", "/" + NEW + "/api")
    t = t.replace("[" + OLD + "]", "[" + NEW + "]")
    open(q, "w", encoding="utf-8").write(t)

# README title
rd = os.path.join(D, "README.md")
if os.path.exists(rd):
    r = open(rd, encoding="utf-8").read().replace(OLD, NEW)
    open(rd, "w", encoding="utf-8").write(r)

print(json.dumps({"name": pkg["name"], "patched": True}, ensure_ascii=False))
