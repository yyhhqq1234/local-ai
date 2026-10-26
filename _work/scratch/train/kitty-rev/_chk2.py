import json
d=json.load(open("data/intent3/v6-mix/tools.json",encoding="utf-8"))
print("工具总数:",d["count"],"schema 数:",len(d["function_schemas"]))
by={t["name"]:t for t in d["tools"]}
for nm in ("kitty_jadx","kitty_rea_trace","kitty_ce","kitty_ops","kitty_status"):
    t=by.get(nm)
    if not t: print(f"  {nm:<18} MISSING"); continue
    ps=", ".join(f"{k}{'*' if k in t['required'] else ''}" for k in t["params"]) or "(无参数)"
    print(f"  {nm:<18} {ps}")
print("\n没有 action 参数的工具数:", sum(1 for t in d["tools"] if "action" not in t["params"]))
print("有 action 参数的工具数  :", sum(1 for t in d["tools"] if "action" in t["params"]))
print("完全无参数的工具:", [t["name"] for t in d["tools"] if not t["params"]][:12])
