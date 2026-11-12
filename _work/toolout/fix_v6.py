"""
修复 v6 词表：
1) 跨类别重复词：只保留主类别条目，其他类别删除该条目（靠 cross_ref 关联）
2) state 里的"餍足地XX"变体：只保留基础词"餍足"
3) 主类别判定规则：
   - 淫荡/淫靡/淫乱/诱人 -> 主类 descriptor（形容状态/气质），state 中删
   - 前凸后翘/晶莹剔透 -> 主类 body（身体描写），state 中删
   - 兴奋/羞耻 -> 主类 emotion（情绪），state 中删
   - 主动 -> 主类 personality（性格），state 中删
   - 疯狂/剧烈 -> 主类 state（行为状态），保留
   - 酥软/瘫软/绵软 -> 主类 state（身体状态），emotion 中已有 cross_ref，OK
"""
import json

d = json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", encoding="utf-8"))

# ── 步骤1：删除 state 中的"餍足地XX"变体，只留"餍足" ──
state_terms = d["state"]["terms"]
to_remove_state = []
for k in state_terms:
    if k.startswith("餍足") and k != "餍足":
        to_remove_state.append(k)
for k in to_remove_state:
    del state_terms[k]
print(f"Removed {len(to_remove_state)} '餍足地XX' variants from state")

# ── 步骤2：跨类别重复词处理 ──
# 定义：word -> (primary_category, [categories to remove from])
DEDUP_RULES = {
    "淫荡":       ("descriptor", ["state"]),
    "淫靡":       ("descriptor", ["state"]),
    "诱人":       ("descriptor", ["state"]),
    "前凸后翘":   ("body",       ["state"]),
    "晶莹剔透":   ("body",       ["state"]),
    "兴奋":       ("emotion",    ["state"]),
    "羞耻":       ("emotion",    ["state"]),
    "主动":       ("personality",["state"]),
}

for word, (primary, remove_from) in DEDUP_RULES.items():
    # 确保主类别有该词
    if word not in d[primary]["terms"]:
        # 从某个 remove_from 中移动过来
        for cat in remove_from:
            if word in d[cat]["terms"]:
                info = d[cat]["terms"].pop(word)
                d[primary]["terms"][word] = info
                break
    # 从其他类别删除
    for cat in remove_from:
        if word in d[cat]["terms"]:
            del d[cat]["terms"][word]
    print(f"  '{word}' -> primary={primary}, removed from {remove_from}")

# ── 步骤3：检查是否还有其他跨类别重复 ──
all_cats = {}
for cat_name, cat in d.items():
    if isinstance(cat, dict) and "terms" in cat:
        for term in cat["terms"]:
            all_cats.setdefault(term, []).append(cat_name)

dups = {t: cats for t, cats in all_cats.items() if len(cats) > 1}
if dups:
    print("\nRemaining duplicates:")
    for t, cats in dups.items():
        print(f"  {t}: {cats}")
else:
    print("\nNo remaining cross-category duplicates.")

# ── 写回 ──
with open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-lexicon-v6.json", "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

total = sum(len(v["terms"]) for v in d.values() if isinstance(v, dict) and "terms" in v)
print(f"\nFinal total: {total} terms")
