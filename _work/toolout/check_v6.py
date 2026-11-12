import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

print("=== state terms ===")
for k in d["state"]["terms"]:
    print(f"  {k}")

print("\n=== descriptor terms ===")
for k in d["descriptor"]["terms"]:
    print(f"  {k}")

print("\n=== personality terms ===")
for k in d["personality"]["terms"]:
    print(f"  {k}")
