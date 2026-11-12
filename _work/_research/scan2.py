import json,ssl,urllib.request
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=60).read()
repos=[
"fyb1214/Huihui-Qwen3.8-27B-Abliterated-Swift-1.5-GSQ-RCO-NInfer",
"WaveCut/Huihui-Qwen3.8-27B-abliterated-NInfer-v3",
"Barding-Defense/Qwen3.8-27B-huihui-abliterated-groupwise-int-NInfer",
"kaushikvira/Qwen3.8-27B-swift-abliterated-nvfp4full-dflash2-NInfer-v3",
"plyfl/Qwopus3.8-27B-Flash-abliterated-ninfer-exp",
]
for r in repos:
    try:
        d=json.loads(get(f"https://huggingface.co/api/models/{r}/tree/main?recursive=true"))
        rows=[((x.get('lfs') or {}).get('size') or x.get('size',0), x['path']) for x in d if x['type']=='file']
        nf=sorted([(s,p) for s,p in rows if p.endswith('.ninfer')])
        print(f"\n=== {r} ===")
        for s,p in nf[:10]: print(f"   {s/1e9:7.2f} GB ({s/2**30:6.2f} GiB)  {p}")
        if not nf: print("   (no .ninfer)", [p for _,p in rows][:8])
    except Exception as e: print(f"\n=== {r} ===\n   ERR {e}")
