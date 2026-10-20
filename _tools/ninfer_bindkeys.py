import json,struct,re,collections
p=r"ninfer-27b-kv-stream-3arch-20261019/model/Ternary-Bonsai-2-27B-ninfer-v3-mtponly.ninfer"
with open(p,"rb") as f:
    hdr=f.read(32); jlen=struct.unpack("<Q",hdr[8:16])[0]; buf=f.read(jlen+64)
j,_=json.JSONDecoder().raw_decode(buf.decode("utf-8",errors="replace").lstrip())
b=j["bindings"]
keys=list(b)
print("bindings n=",len(keys))
# 归类：去数字层号
pat=collections.Counter()
for k in keys:
    kk=re.sub(r"layers/\d+/","layers/N/",k)
    pat[kk]+=1
for kk,c in sorted(pat.items()): print(f"  {kk}  x{c}")
