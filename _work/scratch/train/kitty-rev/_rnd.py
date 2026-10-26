# -*- coding: utf-8 -*-
import re
lines = open("logs/v6/base-all23-fixed.log", encoding="utf-8", errors="replace").read().splitlines()
rounds = {}
cur = 0
for L in lines:
    m = re.match(r"===== 第 (\d)/3 轮", L)
    if m: cur = int(m.group(1)); rounds[cur] = []; continue
    if cur:
        mm = re.match(r"\[(\d+)/23\]\s+(\S+)\s+(PASS|FAIL)", L)
        if mm: rounds[cur].append((int(mm.group(1)), mm.group(2), mm.group(3)))
for r in sorted(rounds):
    rs = rounds[r]
    ok = sum(1 for x in rs if x[2] == "PASS")
    print(f"第{r}轮: 完成 {len(rs)}/23, PASS {ok}", f"= {ok/len(rs)*100:.1f}%" if rs else "")
    if len(rs) >= 23:
        cats = {}
        for i, cat, res in rs:
            cats.setdefault(cat, [0,0]); cats[cat][1]+=1
            if res=="PASS": cats[cat][0]+=1
        for k,(a,b) in sorted(cats.items(), key=lambda x:-x[1][1]):
            print(f"   {k:<20} {a}/{b}")
        fails=[i for i,c,r in rs if r=="FAIL"]
        print(f"   FAIL 题: {fails}")
