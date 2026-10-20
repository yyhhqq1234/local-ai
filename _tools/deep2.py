import json,struct,sys,collections
def load(p):
    with open(p,'rb') as f:
        h=f.read(32); jl=struct.unpack('<Q',h[8:16])[0]; buf=f.read(jl+256)
    return json.JSONDecoder().raw_decode(buf.decode('utf-8',errors='replace').lstrip())[0]
p=sys.argv[1]; j=load(p)
objs=j['objects']
# 找 weight 类对象，打印字段
w=[o for o in objs if str(o.get('id','')).startswith('weight/')][:2]
print("weight object 样例:"); [print("  ",json.dumps(o)[:300]) for o in w]
# 全字段名统计
ks=collections.Counter(k for o in objs for k in o)
print("object 字段:",dict(ks))
# 用 layout/encoding 类字段统计
for fld in ("layout","codec","type","format"):
    c=collections.Counter(str(o.get(fld)) for o in objs if fld in o)
    if c: print(f"字段 {fld}:",dict(c.most_common(12)))
# bindings 样本
b=j['bindings']; items=list(b.items())
print("bindings 样本:")
for k,v in items[:3]: print("  ",k,"->",json.dumps(v)[:160])
for k,v in items:
    if 'layers/0/' in k: print("  ",k,"->",json.dumps(v)[:160])
# text/proposal
txt=j['components']['text']
print("text.proposal:",json.dumps(txt.get('proposal'))[:300])
print("text.resources:",list((txt.get('resources') or {}).keys()))
print("mtp.config keys:",list((j['components']['mtp'].get('config') or {}).keys())[:15])
print("vision:",json.dumps(j['components']['vision'])[:250])
