import json,ssl,urllib.request,urllib.parse
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'curl/8'})
    return urllib.request.urlopen(r,context=ctx,timeout=60).read()
seen={}
for q in ["Coder390 ninfer","Huihui Coder390","Qwen3.8-27B-Coder abliterated","ninfer IQ2 abliterated","ninfer code uncensored","Qwen3.8-27B-Coder390 abliterated"]:
    u="https://huggingface.co/api/models?"+urllib.parse.urlencode({"search":q,"limit":40})
    try:
        d=json.loads(get(u))
        print(f"=== '{q}': {len(d)} ===")
        for m in d:
            mid=m.get("modelId"); tags=m.get("tags") or []
            if mid in seen: continue
            seen[mid]=1
            hit=[x for x in tags if x in ("ninfer","abliterated","uncensored","coder","gguf")]
            if "ninfer" in hit or "abliterated" in hit or "uncensored" in hit:
                print("  ",mid,"|",hit,"| dl",m.get("downloads"))
    except Exception as e: print("ERR",q,e)
