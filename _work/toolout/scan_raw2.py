import json, os, sys
from collections import Counter

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

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

# Write to file with utf-8
out = []
out.append(f"Total records: {total}")
out.append(f"\n=== topic ===")
for k, v in meta_topics.most_common(50):
    out.append(f"  {k}: {v}")
out.append(f"\n=== level ===")
for k, v in meta_levels.most_common(20):
    out.append(f"  {k}: {v}")
out.append(f"\n=== form ===")
for k, v in meta_forms.most_common(20):
    out.append(f"  {k}: {v}")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\scan_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
