import json, os

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"
d = json.load(open(os.path.join(base, "nsfw-lexicon-v4.json"), encoding="utf-8"))

out = []
out.append("=== relationship terms ===")
for k in d.get("relationship", {}).get("terms", {}):
    out.append(f"  {k}")

out.append("")
out.append("=== descriptor terms ===")
for k in d.get("descriptor", {}).get("terms", {}):
    out.append(f"  {k}")

# Also check the glossary r4 to see its categories
out.append("")
out.append("=== nsfw-glossary-r4.jsonl categories ===")
cat_count = {}
with open(os.path.join(base, "nsfw-glossary-r4.jsonl"), encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        rid = obj.get("id", "")
        parts = rid.split("-", 2)
        if len(parts) >= 2:
            cat = parts[1]
            cat_count[cat] = cat_count.get(cat, 0) + 1
for k, v in sorted(cat_count.items()):
    out.append(f"  {k}: {v}")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\v4_detail.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
