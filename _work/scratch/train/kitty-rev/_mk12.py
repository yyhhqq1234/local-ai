# -*- coding: utf-8 -*-
"""从训练集抽 in-domain 样本：6 real-trajectory + 6 tool-route"""
import json, random

src = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
print("训练集总数:", len(rows))

def cat_of(r):
    return (r.get("meta") or {}).get("cat", "?")

real = [r for r in rows if cat_of(r) == "real-trajectory" and len(r.get("tools") or []) > 0]
route = [r for r in rows if cat_of(r) == "tool-route" and len(r.get("tools") or []) > 0]
print("real-trajectory 可用:", len(real), " tool-route 可用:", len(route))

random.seed(20261025)
pick_real = random.sample(real, 6)
pick_route = random.sample(route, 6)

out = []
for r in pick_real:
    out.append({"kind": "real", "cat": "real-trajectory",
                "user": r["messages"][0]["content"],
                "ref": r["messages"][1]["content"] if len(r["messages"]) > 1 else "",
                "tools": r["tools"]})
for r in pick_route:
    out.append({"kind": "route", "cat": "tool-route",
                "user": r["messages"][0]["content"],
                "ref": r["messages"][1]["content"] if len(r["messages"]) > 1 else "",
                "tools": r["tools"]})

json.dump(out, open("data/_indomain12.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写 data/_indomain12.json  共", len(out), "条")
for i, x in enumerate(out, 1):
    print(f"  [{i:>2}] {x['cat']:<18} user={x['user'][:60]}")
