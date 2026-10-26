import json
rows=[json.loads(l) for l in open("data/eval.jsonl",encoding="utf-8") if l.strip()]
# 题号从 1 开始，按文件顺序
want={1,12,13,21}
sub=[r for i,r in enumerate(rows,1) if i in want]
print("总题数",len(rows),"提取",len(sub))
for i,r in enumerate(rows,1):
    if i in want:
        print(f"  题{i}: tool={(r.get('meta') or {}).get('tool')}")
with open("data/eval-toolroute4.jsonl","w",encoding="utf-8") as f:
    for r in sub: f.write(json.dumps(r,ensure_ascii=False)+"\n")
print("→ data/eval-toolroute4.jsonl")
