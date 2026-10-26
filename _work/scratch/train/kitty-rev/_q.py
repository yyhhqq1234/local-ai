import json, collections
for fn in ("data/intent3/v6-mix/train.jsonl",):
    rows=[json.loads(l) for l in open(fn,encoding="utf-8") if l.strip()]
    c=collections.Counter()
    ex=[]
    for r in rows:
        for m in r["messages"]:
            for tc in (m.get("tool_calls") or []):
                if tc["function"]["name"]=="kitty_status":
                    a=tc["function"]["arguments"]
                    c[a]+=1
                    if "action" in a and len(ex)<3: ex.append(a)
    print("kitty_status 参数形态分布:")
    for k,v in c.most_common(): print(f"  {k}  ×{v}")
