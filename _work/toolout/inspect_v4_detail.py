import json, os

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"
d = json.load(open(os.path.join(base, "nsfw-lexicon-v4.json"), encoding="utf-8"))

# Print all terms in relationship and descriptor
print("=== relationship terms ===")
for k in d.get("relationship", {}).get("terms", {}):
    print(f"  {k}")

print("\n=== descriptor terms ===")
for k in d.get("descriptor", {}).get("terms", {}):
    print(f"  {k}")

# Also check the glossary r4 to see its categories
print("\n=== nsfw-glossary-r4.jsonl categories ===")
cat_count = {}
with open(os.path.join(base, "nsfw-glossary-r4.jsonl"), encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        rid = obj.get("id", "")
        # id format like "r4-body-xxx"
        parts = rid.split("-", 2)
        if len(parts) >= 2:
            cat = parts[1]
            cat_count[cat] = cat_count.get(cat, 0) + 1
for k, v in sorted(cat_count.items()):
    print(f"  {k}: {v}")
