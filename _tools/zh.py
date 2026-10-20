import json,ssl,urllib.request,time,io
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def call(prompt,mx=1200,effort=None,extra=None):
    body={"model":"qwen3.8-27b-ablit-swift15-iq2s","messages":[{"role":"user","content":prompt}],
          "max_tokens":mx,"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0}
    if effort: body["reasoning_effort"]=effort
    if extra: body.update(extra)
    b=json.dumps(body,ensure_ascii=False).encode()
    r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=b,
      headers={'Content-Type':'application/json','Content-Length':str(len(b))})
    t=time.time()
    try:
        d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=1200).read())
    except Exception as e:
        return dict(name="",el=time.time()-t,err=str(e))
    el=time.time()-t; c=d['choices'][0]; m=c.get('message',{}); u=d['usage']
    return dict(el=el,fin=c.get('finish_reason'),out=u['completion_tokens'],
                think=u.get('completion_tokens_details',{}).get('reasoning_tokens',0),
                ans=m.get('content') or '',th=m.get('reasoning_content') or '')
cases=[
 ("A 正面约束","用 120 字介绍杭州的城市特点。",None,None),
 ("B 负向约束(原题)","用 120 字介绍杭州，要求不出现'西湖'两个字。",None,None),
 ("C 负向+effort=low","用 120 字介绍杭州，要求不出现'西湖'两个字。","low",None),
 ("D 负向+effort=none","用 120 字介绍杭州，要求不出现'西湖'两个字。","none",None),
 ("E 英文负向","Describe Hangzhou in 120 English words without using the words 'West Lake'.","low",None),
 ("F 中文创意改写","写一段 120 字的杭州城市散文，风格偏抒情。",None,None),
]
res=[]
for n,p,ef,ex in cases:
    r=call(p,1200,ef,ex); r['name']=n; res.append(r)
    print(f"{n:22s} {r.get('el',0):6.1f}s out={r.get('out',0):5d} think={r.get('think',0):5d} ans_len={len(r.get('ans','')):5d} fin={r.get('fin')}")
io.open('_research/zh.json','w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=1))
