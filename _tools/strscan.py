import re,sys,collections
p=sys.argv[1]; pats=[p.lower() for p in sys.argv[2:]]
data=open(p,'rb').read()
seen=collections.Counter()
for m in re.finditer(rb'[ -~]{6,120}', data):
    s=m.group().decode('ascii','ignore')
    low=s.lower()
    if any(x in low for x in pats):
        seen[s]+=1
for s,c in seen.most_common(60): print(f'{c:5d}  {s}')
