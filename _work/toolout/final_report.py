import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

total = 0
cross_count = 0
for cat_name, cat in d.items():
    if isinstance(cat, dict) and "terms" in cat:
        n = len(cat["terms"])
        total += n
        x = sum(1 for t in cat["terms"].values() if "cross_ref" in t)
        cross_count += x
        print(f"  {cat_name:15s} {n:4d}  (cross_ref: {x})")

print(f"\nTotal: {total} terms, cross_ref entries: {cross_count}")
