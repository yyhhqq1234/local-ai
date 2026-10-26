import json
from collections import Counter

def load(p):
    d = json.load(open(p, encoding="utf-8"))
    det = d["detail"]
    return d, {x["i"]: x for x in det}

d6, v6 = load("logs/v6/JUDGE-V6-ALL23.json")
db, base = load("logs/v6/BASE-ALL23-FIXEDSCHEMA-R1.json")

def summ(det, tag):
    n = len(det); p = sum(1 for x in det if x["pass"])
    print(f"{tag}: {p}/{n} = {p/n*100:.1f}%")
    c = Counter()
    for x in det:
        cat = x.get("cat", "?")
        c[(cat, "P")] += 1 if x["pass"] else 0
        c[(cat, "T")] += 1
    for cat in sorted(set(k[0] for k in c)):
        pp = c[(cat, "P")]; tt = c[(cat, "T")]
        print(f"    {cat:<18} {pp}/{tt}")
    return p, n

p6, n6 = summ(d6["detail"], "V6      ")
pb, nb = summ(db["detail"], "BASE原始 ")

print("\n" + "=" * 78)
print("逐题对比（i / cat / BASE / V6 / 变化）")
print("=" * 78)
delta_up = []; delta_down = []
for i in sorted(set(base) | set(v6)):
    b = base.get(i); v = v6.get(i)
    if not b or not v: continue
    bp = b["pass"]; vp = v["pass"]
    mark = "  " if bp == vp else ("↑ " if vp else "↓ ")
    if bp != vp:
        (delta_up if vp else delta_down).append(i)
    print(f"{mark}[{i:>2}] {v.get('cat','?'):<18} BASE={'P' if bp else 'F'} V6={'P' if vp else 'F'}  "
          f"calls={v.get('calls')} chars={v.get('chars')}")

print("\n" + "=" * 78)
print(f"改善（BASE F → V6 P）: {delta_up if delta_up else '无'}")
print(f"退化（BASE P → V6 F）: {delta_down if delta_down else '无'}")
print(f"总分: BASE {pb}/{nb} ({pb/nb*100:.1f}%)  →  V6 {p6}/{n6} ({p6/n6*100:.1f}%)   差 {p6-pb:+d} 题")
