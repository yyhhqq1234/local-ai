import json,ssl,urllib.request,sys
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=60).read()
repos=[
"YukinoKaorisuna/Qwen3.8-27B-Uncensored-ninfer5080-5070ti",
"WaveCut/Qwen3.8-27B-Uncensored-HauhauCS-Aggressive-DFlash2-NInfer-v3",
"WaveCut/Qwen3.8-27B-GSQ-RCO-IQ3_S-NInfer-v3",
"WaveCut/Qwen3.8-Flash-Next-GSQ-RCO-Coder-IQ1_M-NInfer-v3",
"lyf/Qwen3.8-27B-Huihui-Abliterated-NInfer-NVFP4",
"Dragoy/Swift-Qwen3.8-27B-abliterated-NVFP4-NInfer",
"wacomctl672/Swift-Qwen3.8-27B-Uncensored-ninfer3090",
"2beng2/Swift-1.5-Qwen3.8-27B-Uncensored-NVFP4-NInfer",
"kvnxiao/swift-1.5-qwen3.8-27b-orcarouter-dflash2-nvfp4-ninfer",
"fyb1214/Swift-1.5-Qwen3.8-27B-GSQ-RCO-NInfer",
"hamixdd/Swift-1.5-Qwen3.8-27B-W4A16-RTX3090-NInfer-v3",
"nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-GGUF-NInfer",
]
for r in repos:
    try:
        d=json.loads(get(f"https://huggingface.co/api/models/{r}/tree/main?recursive=true"))
        rows=[((x.get('lfs') or {}).get('size') or x.get('size',0), x['path']) for x in d if x['type']=='file']
        nf=[(s,p) for s,p in rows if p.endswith('.ninfer')]
        nf.sort()
        print(f"\n=== {r.split('/')[-1][:60]} ===")
        if not nf: print("   (no .ninfer)")
        for s,p in nf[:12]: print(f"   {s/1e9:7.2f} GB  {p}")
    except Exception as e:
        print(f"\n=== {r} ===\n   ERR {e}")
