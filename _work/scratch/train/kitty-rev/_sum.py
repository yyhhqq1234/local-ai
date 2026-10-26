import json, collections
rows=[json.loads(l) for l in open("data/intent3/v6-mix/train.final.jsonl",encoding="utf-8") if l.strip()]
print("总条数", len(rows))
kinds=collections.Counter((r.get("meta") or {}).get("kind") for r in rows)
print("构成", dict(kinds))
print("带 tools 行", sum(1 for r in rows if "tools" in r))
tj=json.load(open("data/intent3/v6-mix/tools.json",encoding="utf-8"))
print("tools.json 工具数", tj["count"])
# 抽样看一条
for r in rows:
    if (r.get("meta") or {}).get("kind")=="trajectory":
        print("\n轨迹样本消息数", len(r["messages"]), "tools", len(r.get("tools") or []))
        break
