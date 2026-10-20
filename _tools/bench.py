import json,ssl,urllib.request,time,sys
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def call(prompt,mt=64,tag=""):
    body=json.dumps({"model":"qwen3.8-27b-ablit-swift15-iq2s","messages":[{"role":"user","content":prompt}],
      "max_tokens":mt,"temperature":0.0},ensure_ascii=False).encode()
    r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,
      headers={'Content-Type':'application/json','Content-Length':str(len(body))})
    t=time.time(); d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=900).read()); el=time.time()-t
    u=d['usage']; pt=u['prompt_tokens']; ct=u['completion_tokens']
    print(f"[{tag}] prompt={pt} prefill={el:.2f}s ({pt/el:.0f} tok/s) gen={ct} ({ct/max(el,1e-9):.1f} tok/s) cached={u.get('prompt_tokens_details',{}).get('cached_tokens')}")
    return pt
# 构造 ~8K token 的填充文本（英文比中文 token 更可预测）
filler=("The quick brown fox jumps over the lazy dog. " * 20 + "\n")*40
p1=filler+"\n\nSummarize in one sentence what the passage above is about."
call(p1,64,"cold-8K")
call(p1,64,"repeat-8K")     # 缓存命中测试
needle_prompt = filler + "\n\nThe secret code is ZEBRA-4471-QQ. What is the secret code?\n"
call(needle_prompt,32,"needle-8K")
