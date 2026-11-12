import json, os, re
from collections import Counter, defaultdict

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

# 1) Scan meta fields across all records
meta_topics = Counter()
meta_levels = Counter()
meta_forms = Counter()
total = 0

with open(os.path.join(base, "nsfw.jsonl"), encoding="utf-8") as f:
    for line in f:
        total += 1
        obj = json.loads(line)
        m = obj.get("meta", {})
        t = m.get("topic", "")
        if isinstance(t, list):
            for x in t:
                meta_topics[str(x)] += 1
        else:
            meta_topics[str(t)] += 1
        lv = m.get("level", "")
        meta_levels[str(lv) if not isinstance(lv, list) else "|".join(str(x) for x in lv)] += 1
        fo = m.get("form", "")
        meta_forms[str(fo) if not isinstance(fo, list) else "|".join(str(x) for x in fo)] += 1

print(f"Total records: {total}")
print(f"\n=== topic ===")
for k, v in meta_topics.most_common(50):
    print(f"  {k}: {v}")
print(f"\n=== level ===")
for k, v in meta_levels.most_common(20):
    print(f"  {k}: {v}")
print(f"\n=== form ===")
for k, v in meta_forms.most_common(20):
    print(f"  {k}: {v}")
