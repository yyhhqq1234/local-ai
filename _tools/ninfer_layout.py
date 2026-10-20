import json,struct
p=r"ninfer-27b-kv-stream-3arch-20261019/model/Ternary-Bonsai-2-27B-ninfer-v3-mtponly.ninfer"
with open(p,"rb") as f:
    hdr=f.read(32); jlen=struct.unpack("<Q",hdr[8:16])[0]; buf=f.read(jlen+64)
j,_=json.JSONDecoder().raw_decode(buf.decode("utf-8",errors="replace").lstrip())
print("metadata:",json.dumps(j.get("metadata"),ensure_ascii=False)[:800])
print("provenance:",json.dumps(j.get("provenance"),ensure_ascii=False)[:800])
files=j.get("files") or []
print("files n=",len(files)); print(json.dumps(files[:4],ensure_ascii=False)[:600])
objs=j.get("objects") or []
print("objects n=",len(objs),"type",type(objs[0]))
for o in objs[:3]: print("  obj:",json.dumps(o,ensure_ascii=False)[:300])
# 找 o_proj / down_proj
names=[json.dumps(o,ensure_ascii=False) for o in objs]
tgt=[n for n in names if 'o_proj' in n or 'down_proj' in n]
print("targets n=",len(tgt))
for n in tgt[:4]: print("  ",n[:400])
b=j.get("bindings"); print("bindings:",json.dumps(b,ensure_ascii=False)[:600])
u=j.get("uses"); print("uses:",json.dumps(u,ensure_ascii=False)[:300])
