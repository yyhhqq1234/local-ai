import json,struct
p=r"ninfer-27b-kv-stream-3arch-20261019/model/Ternary-Bonsai-2-27B-ninfer-v3-mtponly.ninfer"
with open(p,"rb") as f:
    hdr=f.read(32)
    jlen=struct.unpack("<Q",hdr[8:16])[0]
    print("magic",hdr[:6],"ver",struct.unpack("<H",hdr[6:8])[0],"json_len",jlen,"hash",hdr[16:32].hex())
    buf=f.read(jlen+64)
s=buf.decode("utf-8",errors="replace").lstrip()
j,end=json.JSONDecoder().raw_decode(s)
print("json parsed, consumed",end)
print("top keys",list(j.keys()))
for comp,cv in j.get("components",{}).items():
    print("== comp",comp,"keys",list(cv.keys()))
    cfg=cv.get("config",{}) or {}
    print("   arch",cfg.get("architectures"),"type",cfg.get("model_type"),"layers",cfg.get("num_hidden_layers"),"hidden",cfg.get("hidden_size"),"vocab",cfg.get("vocab_size"))
    for k,v in cv.items():
        if k=="config": continue
        if isinstance(v,list): print("   ",k,"list len",len(v),"first",str(v[0])[:200])
        elif isinstance(v,dict): print("   ",k,"dict keys",list(v)[:10])
        else: print("   ",k,"=",str(v)[:160])
