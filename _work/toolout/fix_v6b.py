"""
第二轮去重：处理剩余跨类别重复词
规则：每个词只保留一个主类别，其他类别删除
"""
import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

# 剩余重复 -> (primary, remove_from)
DEDUP = {
    "湿润":       ("body",      ["action"]),
    "前凸后翘":   ("body",      ["descriptor"]),
    "晶莹剔透":   ("body",      ["descriptor"]),
    "想到":       ("emotion",   ["action"]),
    "完全暴露":   ("action",    ["descriptor"]),
    "快感":       ("emotion",   ["state"]),
    "高潮":       ("emotion",   ["state"]),
    "舒服":       ("emotion",   ["state"]),
    "好舒服":     ("emotion",   ["state"]),
    "好爽":       ("emotion",   ["state"]),
    "好棒":       ("emotion",   ["state"]),
    "好大":       ("emotion",   ["state"]),
    "好厉害":     ("emotion",   ["state"]),
    "欲望":       ("emotion",   ["state"]),
    "满足":       ("emotion",   ["state"]),
    "主人":       ("relationship", ["identity"]),
    "淫荡":       ("descriptor", ["personality"]),
}

for word, (primary, remove_from) in DEDUP.items():
    if word not in d[primary]["terms"]:
        for cat in remove_from:
            if word in d[cat]["terms"]:
                info = d[cat]["terms"].pop(word)
                d[primary]["terms"][word] = info
                break
    for cat in remove_from:
        if word in d[cat]["terms"]:
            del d[cat]["terms"][word]
    print(f"  '{word}' -> primary={primary}, removed from {remove_from}")

# 验证
all_cats = {}
for cat_name, cat in d.items():
    if isinstance(cat, dict) and "terms" in cat:
        for term in cat["terms"]:
            all_cats.setdefault(term, []).append(cat_name)

dups = {t: cats for t, cats in all_cats.items() if len(cats) > 1}
if dups:
    print("\nStill remaining:")
    for t, cats in dups.items():
        print(f"  {t}: {cats}")
else:
    print("\nAll duplicates resolved.")

with open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

total = sum(len(v["terms"]) for v in d.values() if isinstance(v, dict) and "terms" in v)
print(f"Final total: {total} terms")
