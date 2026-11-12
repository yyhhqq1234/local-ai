import json

with open(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v4.jsonl", encoding="utf-8") as f:
    lines = []
    for i, line in enumerate(f):
        if i >= 5:
            break
        lines.append(line)

recs = [json.loads(l) for l in lines]

out = []
for i, rec in enumerate(recs):
    out.append(f"\n===== Record {i} =====")
    out.append(f"keys: {list(rec.keys())}")
    out.append(f"meta: {json.dumps(rec.get('meta',{}), ensure_ascii=False)}")
    for j, msg in enumerate(rec["messages"]):
        role = msg.get("role")
        content = msg.get("content", "")
        out.append(f"\n--- msg[{j}] role={role} len={len(content)} ---")
        out.append(content[:1500])
        if len(content) > 1500:
            out.append(f"... (+{len(content)-1500} more)")

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\inspect_train_v4.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
