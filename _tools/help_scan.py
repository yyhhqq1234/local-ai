import re,sys
data=open(sys.argv[1],'rb').read()
seen=set(); rows=[]
for m in re.finditer(rb'[ -~]{14,200}', data):
    s=m.group().decode('ascii','ignore').strip()
    if '--' not in s: continue
    if not re.match(r'^\s*--[a-z]', s): continue
    key=s.split()[0]
    if key in seen: continue
    seen.add(key); rows.append(s)
for s in sorted(rows): print(s)
