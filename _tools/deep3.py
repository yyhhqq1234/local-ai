import json,struct,sys,collections,re
def load(p):
    with open(p,'rb') as f:
        h=f.read(32); jl=struct.unpack('<Q',h[8:16])[0]; buf=f.read(jl+256)
    return json.JSONDecoder().raw_decode(buf.decode('utf-8',errors='replace').lstrip())[0]
j=load(sys.argv[1]); objs={o['id']:o for o in j['objects']}; b=j['bindings']
def size_of(v):
    if 'object' in v:
        o=objs.get(v['object'],{}); return o.get('bytes',0)
    r=0
    for p in v.get('parts',[]):
        a,z=p['range']; r+=z-a
    return r
tot=collections.Counter(); fam=collections.Counter()
for k,v in b.items():
    comp=k.split('/')[0]
    s=size_of(v); tot[comp]+=s
    kk=re.sub(r'layers/\d+/','layers/N/',k)
    fam[(comp,kk)]+=s
print("组件字节占比:")
S=sum(tot.values())
for c,s in tot.most_common(): print(f"   {c:8s} {s/2**30:7.3f} GiB  {100*s/S:5.1f}%")
print("\ntext 层类型: ")
att=sum(1 for k in b if re.match(r'text/layers/\d+/attention/',k))
gdn=sum(1 for k in b if re.match(r'text/layers/\d+/gdn/',k))
vl=len({re.match(r'vision/layers/(\d+)/',k).group(1) for k in b if k.startswith('vision/layers/')})
print(f"   attention 张量 {att}  gdn 张量 {gdn}  vision 层数 {vl}")
print("\n最大的 12 个张量族（text）:")
for (c,kk),s in fam.most_common(40):
    if c=='text': print(f"   {kk:42s} {s/2**30:7.3f} GiB")
