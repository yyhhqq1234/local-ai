# -*- coding: utf-8 -*-
import json, random

src = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]

def cat_of(r):
    return (r.get("meta") or {}).get("cat", "?")

def user_of(r):
    for m in r["messages"]:
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""

def first_assistant(r):
    for m in r["messages"]:
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""

real = [r for r in rows if cat_of(r) == "real-trajectory" and r.get("tools")]
route = [r for r in rows if cat_of(r) == "tool-route" and r.get("tools")]
print("real:", len(real), " route:", len(route))

random.seed(20261025)
pick = random.sample(real, 6) + random.sample(route, 6)

out = []
for r in pick:
    out.append({"cat": cat_of(r), "system": (r["messages"][0].get("content") or "")[:0],
                "user": user_of(r), "ref": first_assistant(r), "tools": r["tools"]})
json.dump(out, open("data/_indomain12.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote 12")
for i, x in enumerate(out, 1):
    print(f"  [{i:>2}] {x['cat']:<18} user={x['user'][:70]}")
