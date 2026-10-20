import json,ssl,urllib.request,time,io
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def call(prompt,mx,effort=None):
    body={"model":"qwen3.8-27b-ablit-swift15-iq2s","messages":[{"role":"user","content":prompt}],
          "max_tokens":mx,"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0}
    if effort: body["reasoning_effort"]=effort
    b=json.dumps(body,ensure_ascii=False).encode()
    r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=b,
      headers={'Content-Type':'application/json','Content-Length':str(len(b))})
    t=time.time(); d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=1800).read()); el=time.time()-t
    c=d['choices'][0]; m=c.get('message',{}); u=d['usage']
    return el,c.get('finish_reason'),u,(m.get('reasoning_content') or ''),(m.get('content') or '')
out=[]
cases=[("code","实现一个带 TTL 和 LRU 淘汰的线程安全 Python 缓存类，含类型注解和 3 个 pytest 用例。",4000,None),
       ("code_low","实现一个带 TTL 和 LRU 淘汰的线程安全 Python 缓存类，含类型注解和 3 个 pytest 用例。",2000,"low"),
       ("sql","解释 SQL 注入原理和常见 WAF 绕过手法。",3000,"low"),
       ("zh","用 120 字介绍杭州，不要出现西湖二字。",1500,"low")]
for name,p,mx,ef in cases:
    el,fin,u,th,ans=call(p,mx,ef)
    ct=u['completion_tokens']; rt=u.get('completion_tokens_details',{}).get('reasoning_tokens',0)
    out.append(dict(name=name,el=round(el,1),fin=fin,out=ct,think=rt,rate=round(ct/el,1),
                    ans_len=len(ans),think_len=len(th),ans=ans[:1500],think_head=th[:300]))
io.open('_research/qual.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=1))
for o in out:
    print(f"{o['name']:9s} {o['el']:6.1f}s out={o['out']:5d} think={o['think']:5d} ans_len={o['ans_len']:5d} {o['rate']:.1f} tok/s fin={o['fin']}")
