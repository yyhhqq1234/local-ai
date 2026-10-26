# -*- coding: utf-8 -*-
"""用真实 schema 校验训练数据的 tool_calls 参数合法性"""
import json, collections
tj = json.load(open("data/intent3/v6-mix/tools.json", encoding="utf-8"))
P = {t["name"]: set(t["params"].keys()) for t in tj["tools"]}
REQ = {t["name"]: set(t["required"]) for t in tj["tools"]}

bad_params = collections.Counter()   # (tool, 非法键)
missing_req = collections.Counter()
total_calls = 0
for fn in ("data/intent3/v6-mix/train.jsonl", "data/intent3/v6-mix/train.final.jsonl"):
    try: rows = [json.loads(l) for l in open(fn, encoding="utf-8") if l.strip()]
    except FileNotFoundError: continue
    for r in rows:
        for m in r["messages"]:
            if m.get("role") != "assistant": continue
            for c in (m.get("tool_calls") or []):
                nm = c["function"]["name"]; args = json.loads(c["function"]["arguments"])
                total_calls += 1
                if nm not in P: continue
                extra = set(args) - P[nm]
                if extra: bad_params[(fn.split("/")[-1], nm, tuple(sorted(extra)))] += 1
                miss = REQ[nm] - set(args)
                if miss: missing_req[(nm, tuple(sorted(miss)))] += 1
print(f"扫描 tool_call 总数: {total_calls}")
print(f"\n参数键不存在（会被引擎拒/忽略）:")
for (f, nm, extra), c in bad_params.most_common(20):
    print(f"  {f:<20} {nm:<18} 多了 {list(extra)}  ×{c}")
print(f"\n缺必填参数:")
for (nm, miss), c in missing_req.most_common(15):
    print(f"  {nm:<18} 缺 {list(miss)}  ×{c}")
if not bad_params and not missing_req:
    print("  无（全部合法）")
