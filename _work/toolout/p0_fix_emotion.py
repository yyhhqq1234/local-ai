"""
P0-1: 清理 emotion 类"餍足地XX"变体，只留"餍足"
"""
import json

path = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json"
d = json.load(open(path, encoding="utf-8"))

emotion_terms = d["emotion"]["terms"]

# 找出所有"餍足"开头的词
variants = [k for k in emotion_terms if k.startswith("餍足") and k != "餍足"]
print(f"Found {len(variants)} '餍足XX' variants to remove:")
for v in variants:
    print(f"  {v}")
    del emotion_terms[v]

# 确保"餍足"存在
if "餍足" not in emotion_terms:
    # 从 state 中找（之前去重可能移到了 state）
    if "餍足" in d["state"]["terms"]:
        emotion_terms["餍足"] = d["state"]["terms"].pop("餍足")
        print("  Moved '餍足' from state to emotion")
    else:
        # 创建基础条目
        emotion_terms["餍足"] = {
            "meaning": "满足感达到顶峰后的宁静状态",
            "freq": 0,
            "context_examples": []
        }
        print("  Created base '餍足' entry")

with open(path, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

total = sum(len(v["terms"]) for v in d.values() if isinstance(v, dict) and "terms" in v)
print(f"\nDone. Total terms now: {total}")
