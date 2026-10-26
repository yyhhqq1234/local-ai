import re
p="logs/v6/base-all23-fixed.log"
try: lines=open(p,encoding="utf-8",errors="replace").read().splitlines()
except FileNotFoundError: raise SystemExit("no log")
# 截取第1轮
r1=[]; cur=0
for L in lines:
    if "===== 第 1/3 轮" in L: cur=1; continue
    if "===== 第 2/3 轮" in L: cur=0
    if cur and L.startswith("["):
        m=re.match(r"\[(\d+)/\d+\]\s+(\S+)\s+(PASS|FAIL)", L)
        if m: r1.append((int(m.group(1)), m.group(2), m.group(3)))
print(f"第1轮已完成 {len(r1)}/23")
from collections import Counter
c=Counter()
for i,cat,res in r1:
    c[cat] = c.get(cat, [0,0])
    c[cat][1]+=1
    if res=="PASS": c[cat][0]+=1
for k,(ok,tot) in sorted(c.items(), key=lambda x:-x[1][1]):
    print(f"  {k:<22} {ok}/{tot}")
fails=[(i,cat) for i,cat,res in r1 if res=="FAIL"]
print("FAIL 题:", fails)
