import json,ssl,urllib.request,struct
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def rng(u,a,b):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8','Range':f'bytes={a}-{b}'})
    return urllib.request.urlopen(r,context=ctx,timeout=90).read()
repo="fyb1214/Huihui-Qwen3.8-27B-Abliterated-Swift-1.5-GSQ-RCO-NInfer"
for f in ["Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer","Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_XXS-mtp.ninfer"]:
    u=f"https://huggingface.co/{repo}/resolve/main/{f}"
    h=rng(u,0,31); ver=struct.unpack('<H',h[6:8])[0]; jl=struct.unpack('<Q',h[8:16])[0]
    j,_=json.JSONDecoder().raw_decode(rng(u,32,32+jl+128).decode('utf-8',errors='replace').lstrip())
    c=j['components']; t=c.get('text',{}).get('config',{})
    print(f"{f}\n  magic={h[:6]} ver=v{ver} bindings={len(j.get('bindings',{}))} meta={j.get('metadata')}")
    print(f"  components={list(c)} arch={t.get('architectures')} L={t.get('num_hidden_layers')} H={t.get('hidden_size')}")
    print(f"  provenance.recipe={j.get('provenance',{}).get('recipe')} src={list((j.get('provenance',{}).get('sources') or {}).keys())}")
