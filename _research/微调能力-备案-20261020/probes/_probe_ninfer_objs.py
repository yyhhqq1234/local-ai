import json, struct, os, collections

p = r"D:\BaiduNetdiskDownload\Local-AI\infer-27b-kv-stream-3arch-20261019\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer"
with open(p, "rb") as f:
    hdr = f.read(32)
    jlen = struct.unpack("<Q", hdr[8:16])[0]
    buf = f.read(jlen + 64)
j, _ = json.JSONDecoder().raw_decode(buf.decode("utf-8", errors="replace").lstrip())

objs = j["objects"]
kinds = collections.Counter(o.get("kind") for o in objs)
print("kinds:", dict(kinds))
enc = collections.Counter(o.get("encoding") for o in objs)
print("encodings:", dict(enc))

w = [o for o in objs if o.get("kind") == "weight" or o.get("kind") == "tensor"]
print("weight-ish n=", len(w))
for o in w[:6]:
    print("  W:", json.dumps(o, ensure_ascii=False)[:400])

# 看 bindings / uses
print("bindings sample:", json.dumps(j.get("bindings"), ensure_ascii=False)[:500])
uses = j.get("uses")
print("uses:", json.dumps(uses, ensure_ascii=False)[:400])

# 全量 object 键集合
keys = collections.Counter()
for o in objs:
    keys.update(o.keys())
print("object keys:", dict(keys))

# 找带 quant 信息的
q = [o for o in objs if any(k for k in o if "quant" in k.lower() or "dtype" in k.lower() or "shape" in k.lower())]
print("quant-meta objs n=", len(q))
for o in q[:5]:
    print("  Q:", json.dumps(o, ensure_ascii=False)[:400])

names = [o.get("id", "") for o in objs]
import re
lay = [n for n in names if re.search(r"blk\.\d+|layers\.\d+", n)]
print("layer-tensors n=", len(lay))
for n in lay[:8]:
    print("   ", n)
