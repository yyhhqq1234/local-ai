import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

# 找出所有跨类别重复
all_cats = {}
for cat_name, cat in d.items():
    if isinstance(cat, dict) and "terms" in cat:
        for term in cat["terms"]:
            all_cats.setdefault(term, []).append(cat_name)

dups = {t: cats for t, cats in all_cats.items() if len(cats) > 1}
print("Remaining duplicates:")
for t, cats in dups.items():
    print(f"  {t}: {cats}")

# 逐个处理：保留第一个类别，删掉其余
for word, cats in list(dups.items()):
    primary = cats[0]  # 保留第一个
    remove_from = cats[1:]
    for cat in remove_from:
        if word in d[cat]["terms"]:
            del d[cat]["terms"][word]
    print(f"  '{word}' -> kept in {primary}, removed from {remove_from}")

# 最终验证
all_cats2 = {}
for cat_name, cat in d.items():
    if isinstance(cat, dict) and "terms" in cat:
        for term in cat["terms"]:
            all_cats2.setdefault(term, []).append(cat_name)

dups2 = {t: cats for t, cats in all_cats2.items() if len(cats) > 1}
if dups2:
    print("\nSTILL remaining:")
    for t, cats in dups2.items():
        print(f"  {t}: {cats}")
else:
    print("\nAll clean.")

with open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

total = sum(len(v["terms"]) for v in d.values() if isinstance(v, dict) and "terms" in v)
print(f"Final total: {total} terms")
