import json, os, re
from collections import Counter

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

# Load existing v4 lexicon terms for comparison
d = json.load(open(os.path.join(base, "nsfw-lexicon-v4.json"), encoding="utf-8"))
existing_terms = set()
for cat in d.values():
    if isinstance(cat, dict) and "terms" in cat:
        for term in cat["terms"]:
            existing_terms.add(term)

print(f"Existing v4 terms: {len(existing_terms)}")

# Collect all assistant texts
all_texts = []
with open(os.path.join(base, "nsfw.jsonl"), encoding="utf-8") as f:
    for line in f:
        obj = json.loads(line)
        for msg in obj.get("messages", []):
            if msg.get("role") == "assistant":
                all_texts.append(msg["content"])

print(f"Total texts: {len(all_texts)}")

# N-gram frequency: 2-6 char Chinese sequences
# Use a simple approach: split by non-Chinese chars, then count n-grams
ng_counter = Counter()
for text in all_texts:
    # Extract Chinese character runs
    runs = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    for run in runs:
        for n in [2, 3, 4]:
            for i in range(len(run) - n + 1):
                ng = run[i:i+n]
                ng_counter[ng] += 1

# Filter: only words with freq >= 30, not already in existing terms
# Also filter out very common function words
stop_words = set('的了是在有和与就都也很不这那被把让给从到对于着过能会要可以而且但是所以因为如果虽然然后还有没有自己别人什么怎么这样那样一样一些一些'.replace(' ',''))
stop_bigrams = {'的','了','是','在','有','和','与','就','都','也','很','不','这','那','被','把','让','给','从','到','对','于','着','过','能','会','要','可','以','而','且','但','是','所','因','为','如','果','虽','然','后','还','没','有','自','己','别','人','什','么','怎','样','一','些'}

new_candidates = {}
for ng, cnt in ng_counter.items():
    if cnt < 30:
        continue
    if ng in existing_terms:
        continue
    # Skip if it's a substring of a longer word that's also in the candidates
    # (We'll handle this later)
    new_candidates[ng] = cnt

# Sort by frequency
sorted_new = sorted(new_candidates.items(), key=lambda x: -x[1])
out_lines = [f"New candidates (freq>=30, not in v4): {len(sorted_new)}"]
for ng, cnt in sorted_new[:500]:
    out_lines.append(f"  {ng}: {cnt}")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\full_scan_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out_lines))
print(f"Done. Top 500 shown.")
