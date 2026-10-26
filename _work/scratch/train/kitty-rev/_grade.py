import json, sys, importlib.util
spec = importlib.util.spec_from_file_location("nq", "logs/v6/nsfw_qa.py")
m = importlib.util.module_from_spec(spec)
sys.modules["nq"] = m
spec.loader.exec_module(m)
rows = [json.loads(l) for l in open("data/intent3/w3-bodies.jsonl", encoding="utf-8") if l.strip()]
level_fn = None
for name in ("grade", "classify", "level_of", "judge"):
    if hasattr(m, name):
        level_fn = getattr(m, name); print("用函数:", name); break
if not level_fn:
    print("找不到分级函数，列出可用:", [x for x in dir(m) if not x.startswith("_")][:30]); raise SystemExit(1)
out = []
for r in rows:
    a = r["messages"][1]["content"]
    try:
        lv = level_fn(a)
    except TypeError:
        lv = level_fn(a, None) if len(rows) else None
    lvv = lv[0] if isinstance(lv, (tuple, list)) else lv
    out.append((r["id"], lvv, len(a)))
from collections import Counter
print("分级分布:", Counter(x[1] for x in out))
seeds = [x for x in out if x[1] in (2, 3, "L2", "L3")]
print(f"L2/L3 种子 {len(seeds)} 条:")
for s in seeds[:30]: print("  ", s)
