import json,ssl,urllib.request,urllib.parse
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=40).read()
for q in ["ninfer","NInfer","ninfer-v3"]:
    u="https://huggingface.co/api/models?"+urllib.parse.urlencode({"search":q,"limit":40})
    try:
        d=json.loads(get(u))
        print(f"=== search '{q}': {len(d)} ===")
        for m in d[:25]: print("  ",m.get("modelId"),"| dl",m.get("downloads"),"| tags",[t for t in (m.get("tags") or []) if t in ("gguf","ninfer","uncensored","abliterated")][:4])
    except Exception as e: print("ERR",q,e)
