import zlib,struct,base64,json,ssl,urllib.request,time
# 生成 96x96 PNG：上半红、下半蓝，中间一个白色方块
W=H=96
raw=b''
for y in range(H):
    row=b'\x00'
    for x in range(W):
        if 32<=x<64 and 32<=y<64: row+=b'\xff\xff\xff'
        elif y<H//2: row+=b'\xff\x00\x00'
        else: row+=b'\x00\x00\xff'
    raw+=row
def chunk(t,d):
    c=t+d; return struct.pack('>I',len(d))+c+struct.pack('>I',zlib.crc32(c)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',W,H,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')
open('_research/testimg.png','wb').write(png)
b64=base64.b64encode(png).decode()
print("png bytes:",len(png),"b64 len:",len(b64))
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
body=json.dumps({"model":"qwen3.8-27b-ablit-swift15-iq2s","messages":[{"role":"user","content":[
 {"type":"text","text":"这张图里有哪些颜色？白色方块在什么位置？用中文简短回答。"},
 {"type":"image_url","image_url":{"url":"data:image/png;base64,"+b64}}]}],
 "max_tokens":200,"temperature":0.0},ensure_ascii=False).encode()
r=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,
 headers={'Content-Type':'application/json','Content-Length':str(len(body))})
t=time.time()
d=json.loads(urllib.request.urlopen(r,context=ctx,timeout=900).read()); el=time.time()-t
c=d['choices'][0]; m=c.get('message',{})
print(f"elapsed={el:.2f}s finish={c.get('finish_reason')} usage={d.get('usage')}")
print("--- content ---"); print((m.get('content') or '')[:600])
