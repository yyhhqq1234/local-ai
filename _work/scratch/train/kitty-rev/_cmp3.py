import json, os
def load(p): return json.load(open(p,encoding="utf-8")) if os.path.exists(p) else None
a=load("logs/v5/JUDGE-ALL23-V5.json")                  # 错schema
b=load("logs/v5/JUDGE-ALL23-V5-REALSCHEMA.json")       # 对schema
c=load("logs/v5/JUDGE-ALL23-V5-FINAL.json")            # 对schema+need1+兜底
hdr=f"{'分类':<22}{'错schema':>11}{'对schema':>11}{'终版':>11}"
print(hdr); print("-"*len(hdr))
cats=sorted(set(a["byCat"])|set(b["byCat"])|set(c["byCat"]))
for k in cats:
    f=lambda d: f"{d['byCat'].get(k,{}).get('pass',0)}/{d['byCat'].get(k,{}).get('total',0)}"
    print(f"{k:<22}{f(a):>11}{f(b):>11}{f(c):>11}")
print("-"*len(hdr))
print(f"{'总计':<22}{str(a['pass'])+'/'+str(a['total']):>11}{str(b['pass'])+'/'+str(b['total']):>11}{str(c['pass'])+'/'+str(c['total']):>11}")
print("\n终版逐题：")
for d in c["detail"]:
    print(f"  {d['i']:>2} [{d['cat']:<18}] {'PASS' if d['pass'] else 'FAIL'}  {d['why'][:66]}")
