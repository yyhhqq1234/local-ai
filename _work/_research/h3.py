import json,ssl,urllib.request,struct
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def rng(u,a,b):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8','Range':f'bytes={a}-{b}'})
    return urllib.request.urlopen(r,context=ctx,timeout=90).read()
for repo,f in [("fyb1214/Huihui-Qwen3.8-27B-Abliterated-Ternary-Bonsai-2-NInfer","Huihui-Qwen3.8-27B-abliterated-Ternary-Bonsai-PQ2_0-mtp.ninfer"),
               ("emiltsoi/Ternary-Bonsai-2-27B-Uncensored-Heretic-NInfer","Ternary-Bonsai-2-27B-Heretic-ninfer.ninfer")]:
    u=f"https://hf-mirror.com/{repo}/resolve/main/{f}"
    h=rng(u,0,31); ver=struct.unpack('<H',h[6:8])[0]; jl=struct.unpack('<Q',h[8:16])[0]
    j,_=json.JSONDecoder().raw_decode(rng(u,32,32+jl+128).decode('utf-8',errors='replace').lstrip())
    c=j['components']; t=c.get('text',{}).get('config',{})
    print(f"{repo.split('/')[-1]} / {f}")
    print(f"  magic={h[:6]} v{ver} bindings={len(j.get('bindings',{}))} meta={j.get('metadata')}")
    print(f"  comps={list(c)} arch={t.get('architectures')} L={t.get('num_hidden_layers')} H={t.get('hidden_size')}")
    print(f"  recipe={j.get('provenance',{}).get('recipe')}")
