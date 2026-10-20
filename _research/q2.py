import json,ssl,urllib.request,urllib.parse
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=60).read()
for q in ["ninfer uncensored coder","ninfer abliterated 27b","Coder390 ninfer","ninfer coding"]:
    u="https://huggingface.co/api/models?"+urllib.parse.urlencode({"search":q,"limit":30})
    try:
        d=json.loads(get(u)); print(f"=== '{q}': {len(d)} ===")
        for m in d[:15]:
            t=m.get("tags") or []
            print("  ",m.get("modelId"),"|",[x for x in t if x in ("uncensored","abliterated","ninfer","gguf","coder")][:4])
    except Exception as e: print("ERR",q,e)
