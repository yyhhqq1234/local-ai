import json, collections
d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\local-pack\qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer.conversion.json", encoding="utf-8"))
print("formats:", {k:v for k,v in d["formats"].items() if "iq2" in k or "iq3" in k})
# 从 methods 的 sources 里挖真实 gguf 类型标签
tags = collections.Counter()
for m in d["methods"]:
    for s in (m.get("sources") or []):
        if "[" in s and "]" in s:
            tags[s.split("[")[1].split("]")[0]] += 1
print("source tags:", dict(tags))
