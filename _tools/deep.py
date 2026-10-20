import json,struct,sys,collections
def load(p):
    with open(p,'rb') as f:
        h=f.read(32); jl=struct.unpack('<Q',h[8:16])[0]; buf=f.read(jl+256)
    return json.JSONDecoder().raw_decode(buf.decode('utf-8',errors='replace').lstrip())[0]
for p in sys.argv[1:]:
    j=load(p); print("="*70); print(p.split('/')[-1])
    objs=j.get('objects') or []
    enc=collections.Counter(); encbytes=collections.Counter()
    for o in objs:
        e=o.get('encoding','?'); enc[e]+=1; encbytes[e]+=o.get('bytes',0)
    print(f"objects={len(objs)}  payload={sum(encbytes.values())/2**30:.2f} GiB  bindings={len(j.get('bindings',{}))}")
    print("encoding 分布:")
    for e,c in encbytes.most_common(12):
        print(f"   {e:24s} n={enc[e]:5d}  {c/2**30:7.3f} GiB")
    uses=j.get('uses') or []
    pol=collections.Counter(u.get('activation_policy','?') for u in uses)
    print("activation_policy:",dict(pol))
    aux=collections.Counter(k for u in uses for k in (u.get('auxiliaries') or {}))
    print("auxiliaries:",dict(aux))
    for n,c in (j.get('components') or {}).items():
        cfg=c.get('config') or {}
        keep={k:cfg[k] for k in ('architectures','num_hidden_layers','hidden_size','vocab_size','num_experts','quantization_config','max_position_embeddings') if k in cfg}
        print(f"  comp {n}: {keep} extra_keys={[k for k in c if k!='config']}")
