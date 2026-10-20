import json,struct,re,collections
def load(p):
    with open(p,'rb') as f:
        h=f.read(32); jl=struct.unpack('<Q',h[8:16])[0]; buf=f.read(jl+256)
    return json.JSONDecoder().raw_decode(buf.decode('utf-8',errors='replace').lstrip())[0]
j=load("model/Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer")
objs={o['id']:o for o in j['objects']}; b=j['bindings']
v={k:x for k,x in b.items() if k.startswith('vision/')}
print(f"vision bindings = {len(v)}")
fam=collections.Counter(re.sub(r'layers/\d+/','layers/N/',k) for k in v)
print("family:")
for k,c in sorted(fam.items()): print(f"   {c:3d}  {k}")
# 组件 config 全文
print("\nvision config keys:", list((j['components']['vision'].get('config') or {}).keys())[:20])
cfgj=j['components']['vision'].get('config') or {}
print("vision config:", json.dumps({k:cfgj[k] for k in list(cfgj)[:14]}, ensure_ascii=False)[:600])
print("vision target:", j['components']['vision'].get('target'))
print("vision resources:", list((j['components']['vision'].get('resources') or {}).keys()))
# 视觉张量格式
fmt=collections.Counter()
for k,x in v.items():
    if 'object' in x: fmt[objs.get(x['object'],{}).get('format','?')]+=1
    else: fmt['(parts)']+=len(x.get('parts',[]))
print("vision formats:", dict(fmt))
# text 里是否有 multimodal 相关
mm=[k for k in b if any(s in k for s in ('image','media','patch','merger','projector','mm'))]
print("text 侧多模态相关键:", mm[:10])
