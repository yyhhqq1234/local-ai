import json,ssl,urllib.request
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=60).read()
repos=["fyb1214/Huihui-Qwen3.8-27B-Abliterated-Ternary-Bonsai-2-NInfer",
"emiltsoi/Ternary-Bonsai-2-27B-Uncensored-Heretic-NInfer",
"WaveCut/Ternary-Bonsai-2-27B-NInfer-v3",
"fyb1214/Swift-Bonsai-2-27B-NInfer",
"Hikari07jp/Ternary-Bonsai-2-27B-Abliterated-GGUF"]
for r in repos:
    try:
        d=json.loads(get(f"https://hf-mirror.com/api/models/{r}/tree/main?recursive=true"))
        rows=[((x.get('lfs') or {}).get('size') or x.get('size',0), x['path']) for x in d if x['type']=='file']
        mf=sorted([(s,p) for s,p in rows if p.endswith(('.ninfer','.gguf'))])
        print(f"\n=== {r} ===")
        for s,p in mf[:8]: print(f"   {s/1e9:7.2f} GB ({s/2**30:6.2f} GiB)  {p}")
        if not mf: print("   ", [p for _,p in rows][:6])
    except Exception as e: print(f"\n=== {r} ===\n   ERR {e}")
