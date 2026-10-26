import json,urllib.request,urllib.error
cands=["qwen3.8-27b-ablit-swift15-iq2s","qwen3.8-27b-kittyrev-v5-iq2s-mtp","qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer"]
for m in cands:
    body=json.dumps({"model":m,"messages":[{"role":"user","content":"hi"}],"max_tokens":4}).encode()
    req=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r:
            d=json.loads(r.read())
            print(m,"->",r.status,"content=",repr(d["choices"][0]["message"].get("content"))[:60])
    except urllib.error.HTTPError as e:
        print(m,"->",e.code,e.read()[:180])
    except Exception as e:
        print(m,"-> ERR",type(e).__name__,e)
