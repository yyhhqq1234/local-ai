import json,ssl,urllib.request,struct,sys
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def rng(url,a,b):
    r=urllib.request.Request(url,headers={'User-Agent':'curl/8','Range':f'bytes={a}-{b}'})
    return urllib.request.urlopen(r,context=ctx,timeout=90).read()
def probe("fyb1214/Huihui-Qwen3.8-27B-Abliterated-Swift-1.5-GSQ-RCO-NInfer","Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer")
    u=f"https://huggingface.co/{repo}/resolve/main/{path}"
    h=rng(u,0,31)
    if h[:6]!=b'NINFER': print(f"  {path}: NOT NINFER"); return
    ver=struct.unpack('<H',h[6:8])[0]; jlen=struct.unpack('<Q',h[8:16])[0]
    buf=rng(u,32,32+jlen+64)
    j,_=json.JSONDecoder().raw_decode(buf.decode('utf-8',errors='replace').lstrip())
    comps=j.get('components',{})
    b=len(j.get('bindings',{})); meta=j.get('metadata',{}); prov=j.get('provenance',{})
    print(f"  {path}")
    print(f"    ver=v{ver} json={jlen}B bindings={b} meta={json.dumps(meta,ensure_ascii=False)[:120]}")
    for n,c in comps.items():
        cfg=c.get('config') or {}
        print(f"    comp {n}: arch={cfg.get('architectures')} type={cfg.get('model_type')} L={cfg.get('num_hidden_layers')} H={cfg.get('hidden_size')} experts={cfg.get('num_experts')} quant={c.get('quant')}")
    src=(prov.get('sources') or {})
    print(f"    recipe={prov.get('recipe')} sources={list(src.keys())}")
probe("fyb1214/Huihui-Qwen3.8-27B-Abliterated-Swift-1.5-GSQ-RCO-NInfer","Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer")
