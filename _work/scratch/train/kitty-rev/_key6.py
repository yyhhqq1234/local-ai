import json
rows=[json.loads(l) for l in open("data/eval.jsonl",encoding="utf-8") if l.strip()]
want={1,8,10,13,21,22}
sub=[r for i,r in enumerate(rows,1) if i in want]
print("总题数",len(rows),"抽取",len(sub))
for i,r in enumerate(rows,1):
    if i in want:
        m=r.get('meta') or {}
        print(f"  题{i}: cat={m.get('cat')} tool={m.get('tool','')}")
with open("data/eval-key6.jsonl","w",encoding="utf-8") as f:
    for r in sub: f.write(json.dumps(r,ensure_ascii=False)+"\n")
print("→ data/eval-key6.jsonl")
