import json,ssl,urllib.request,time,io
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def call(p,mx=1200,ef=None):
    body={"model":"qwen3.8-27b-ablit-swift15-iq2s","messages":[{"role":"user","content":p}],
          "max_tokens":mx,"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0}
    if ef: body["reasoning_effort"]=ef
    b=json.dumps(body,ensure_ascii=False).encode()
    r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=b,
      headers={'Content-Type':'application/json','Content-Length':str(len(b))})
    t=time.time(); d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=1200).read()); el=time.time()-t
    c=d['choices'][0]; m=c.get('message',{}); u=d['usage']
    return el,c.get('finish_reason'),u['completion_tokens'],u.get('completion_tokens_details',{}).get('reasoning_tokens',0),m.get('content') or '',m.get('reasoning_content') or ''
cases=[("G 无字数约束","写一段散文，介绍杭州这座城市的气质。",None),
       ("H 模糊量词","用两三句话介绍一下杭州。",None),
       ("I 精确字数+low","用 120 字介绍杭州的城市特点。","low"),
       ("J 精确字数+budget提示","用 120 字介绍杭州的城市特点。先直接给出正文，不要数字数。",None)]
res=[]
for n,p,ef in cases:
    el,fin,out,th,ans,tht=call(p,1200,ef)
    print(f"{n:26s} {el:6.1f}s out={out:5d} think={th:5d} ans={len(ans):5d} fin={fin}")
    res.append(dict(name=n,el=el,fin=fin,out=out,think=th,ans=ans,th=tht[:400]))
io.open('_research/zh2.json','w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=1))
