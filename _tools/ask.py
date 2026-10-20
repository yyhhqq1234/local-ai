import json,ssl,urllib.request,sys,time
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
prompt=sys.argv[1] if len(sys.argv)>1 else "用 Python 写一个快速排序，只给代码。"
mt=int(sys.argv[2]) if len(sys.argv)>2 else 300
body=json.dumps({"model":"qwen3.8-27b-ablit-swift15-iq2s",
 "messages":[{"role":"user","content":prompt}],
 "max_tokens":mt,"temperature":1.0,"top_p":0.95,"top_k":20,"min_p":0},ensure_ascii=False).encode('utf-8')
r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,
 headers={'Content-Type':'application/json','Content-Length':str(len(body))})
t=time.time()
d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=600).read())
el=time.time()-t
c=d['choices'][0]; m=c.get('message',{})
u=d.get('usage') or {}
print(f"elapsed={el:.2f}s finish={c.get('finish_reason')} usage={u}")
rc=m.get('reasoning_content') or ''
ct=m.get('content') or ''
print(f"reasoning_len={len(rc)} content_len={len(ct)}")
if u.get('completion_tokens') and el: print(f"decode≈{u['completion_tokens']/el:.1f} tok/s")
print("--- content ---"); print(ct[:700])
