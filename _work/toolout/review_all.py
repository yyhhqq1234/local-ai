import json, os, re
from collections import Counter

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"
out = []

# ════════════════════════════════════════
# 1) 词表 v6 结构审查
# ════════════════════════════════════════
d = json.load(open(os.path.join(base, "nsfw-lexicon-v6.json"), encoding="utf-8"))

total_terms = 0
issues = []

for cat_name, cat in d.items():
    if not isinstance(cat, dict) or "terms" not in cat:
        continue
    n = len(cat["terms"])
    total_terms += n
    for term, info in cat["terms"].items():
        if not isinstance(info, dict):
            issues.append(f"[{cat_name}] {term}: not a dict")
            continue
        if "meaning" not in info:
            issues.append(f"[{cat_name}] {term}: missing 'meaning'")
        if "freq" not in info:
            issues.append(f"[{cat_name}] {term}: missing 'freq'")
        if info.get("freq", -1) == 0:
            issues.append(f"[{cat_name}] {term}: freq=0 (not found in raw data)")

out.append(f"=== 1) 词表 v6 ===")
out.append(f"Total terms: {total_terms}")
out.append(f"Issues: {len(issues)}")
for i in issues[:30]:
    out.append(f"  {i}")
if len(issues) > 30:
    out.append(f"  ... +{len(issues)-30} more")

# ════════════════════════════════════════
# 2) 训练数据文件审查
# ════════════════════════════════════════
out.append(f"\n=== 2) 训练数据文件 ===")

with open(os.path.join(base, "final-nsfw.jsonl"), encoding="utf-8") as f:
    first_line = f.readline().strip()
    rec = json.loads(first_line)
    out.append(f"final-nsfw.jsonl: first record keys = {list(rec.keys())}")
    if "messages" in rec:
        out.append(f"  messages count = {len(rec['messages'])}")
        out.append(f"  msg[0] role = {rec['messages'][0].get('role','?')}")
        if len(rec['messages']) > 1:
            out.append(f"  msg[1] role = {rec['messages'][1].get('role','?')}")
    if "meta" in rec:
        out.append(f"  meta = {rec['meta']}")

count = 0
with open(os.path.join(base, "final-nsfw.jsonl"), encoding="utf-8") as f:
    for line in f:
        count += 1
out.append(f"final-nsfw.jsonl: {count} lines")

train_v4_path = os.path.join(base, "nsfw-train-v4.jsonl")
if os.path.exists(train_v4_path):
    count = 0
    with open(train_v4_path, encoding="utf-8") as f:
        for line in f:
            count += 1
    out.append(f"nsfw-train-v4.jsonl: {count} lines")
    with open(train_v4_path, encoding="utf-8") as f:
        first = json.loads(f.readline())
    out.append(f"  first record keys = {list(first.keys())}")
    if "messages" in first:
        out.append(f"  messages count = {len(first['messages'])}")
        content = str(first["messages"][0].get("content",""))
        out.append(f"  msg[0] content preview = {content[:200]}")
    if "meta" in first:
        out.append(f"  meta = {first['meta']}")

cov_path = os.path.join(base, "nsfw-coverage.json")
if os.path.exists(cov_path):
    cov = json.load(open(cov_path, encoding="utf-8"))
    out.append(f"\nnsfw-coverage.json keys = {list(cov.keys())[:10]}")
    if isinstance(cov, dict):
        for k in list(cov.keys())[:5]:
            v = cov[k]
            if isinstance(v, (int, float)):
                out.append(f"  {k} = {v}")
            elif isinstance(v, dict):
                out.append(f"  {k} = dict({len(v)})")
            elif isinstance(v, list):
                out.append(f"  {k} = list({len(v)})")

for gf in ["nsfw-glossary.jsonl", "nsfw-glossary-v2.jsonl", "nsfw-glossary-v3-new.jsonl", "nsfw-glossary-r4.jsonl"]:
    gf_path = os.path.join(base, gf)
    if os.path.exists(gf_path):
        count = 0
        with open(gf_path, encoding="utf-8") as f:
            for line in f:
                count += 1
        out.append(f"{gf}: {count} lines")

# ════════════════════════════════════════
# 3) 训练数据分布
# ════════════════════════════════════════
out.append(f"\n=== 3) 训练数据分布 ===")

stype_counter = Counter()
level_counter = Counter()
topic_counter = Counter()
total_train = 0
with open(train_v4_path, encoding="utf-8") as f:
    for line in f:
        total_train += 1
        rec = json.loads(line)
        if "meta" in rec:
            m = rec["meta"]
            stype_counter[m.get("stype", "?")] += 1
            level_counter[m.get("level", "?")] += 1
            topic = m.get("topic", "?")
            if isinstance(topic, list):
                for t in topic:
                    topic_counter[str(t)] += 1
            else:
                topic_counter[str(topic)] += 1

out.append(f"Train v4 total: {total_train}")
out.append(f"stype distribution: {dict(stype_counter)}")
out.append(f"level distribution: {dict(level_counter)}")
out.append(f"topic distribution (top 20):")
for k, v in topic_counter.most_common(20):
    out.append(f"  {k}: {v}")

# ════════════════════════════════════════
# 4) 词表与训练数据一致性
# ════════════════════════════════════════
out.append(f"\n=== 4) 词表与训练数据一致性 ===")

# 检查训练数据中是否有【类别】标记
category_markers = []
with open(train_v4_path, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 10:
            break
        category_markers.extend(re.findall(r'【(\w+)】', line))
out.append(f"Category markers in first 10 train records: {category_markers[:20]}")

lexicon_categories = [cat for cat in d.keys() if isinstance(d[cat], dict) and "terms" in d[cat]]
out.append(f"Lexicon v6 categories: {lexicon_categories}")

# 检查训练数据中是否包含词表中的高频词
high_freq_words = []
for cat_name, cat in d.items():
    if not isinstance(cat, dict) or "terms" not in cat:
        continue
    for term, info in cat["terms"].items():
        if info.get("freq", 0) >= 100:
            high_freq_words.append((term, cat_name, info["freq"]))

high_freq_words.sort(key=lambda x: -x[2])
out.append(f"\nHigh-freq words (>=100): {len(high_freq_words)}")

# 在原始数据中验证这些词确实出现
raw_text_sample = ""
with open(os.path.join(base, "final-nsfw.jsonl"), encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 100:
            break
        raw_text_sample += line

missing_in_raw = []
for word, cat, freq in high_freq_words[:50]:
    if word not in raw_text_sample:
        missing_in_raw.append(f"{word} ({cat}, freq={freq})")

out.append(f"High-freq words not found in first 100 raw lines: {len(missing_in_raw)}")
for m in missing_in_raw[:10]:
    out.append(f"  {m}")

# ════════════════════════════════════════
# 5) 潜在问题清单
# ════════════════════════════════════════
out.append(f"\n=== 5) 潜在问题 ===")
out.append("1. nsfw-train-v4.jsonl 生成时间 vs 词表 v6 更新时间：需确认训练数据是否基于 v6 词表")
out.append("2. nsfw-coverage.json 可能未反映 v6 新增词（genre/identity/personality 三大类）")
out.append("3. cross_ref 机制在训练数据中如何体现？（训练数据中是否有跨类别引用？）")
out.append("4. 词表 v6 的 502 词中，有多少在训练数据的 system prompt 中被实际引用？")
out.append("5. 长尾词（freq < 10）是否需要进入训练数据？还是只作为参考？")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\review_all.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
