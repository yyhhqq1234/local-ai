import json, struct, os, collections, re, glob

MODEL_DIR = r"D:\BaiduNetdiskDownload\Local-AI\infer-27b-kv-stream-3arch-20261019\model"
cands = glob.glob(os.path.join(MODEL_DIR, "*.ninfer"))
print("found:", [(os.path.basename(c), round(os.path.getsize(c)/2**30, 2)) for c in cands])
p = [c for c in cands if "Huihui" in os.path.basename(c)]
p = p[0] if p else cands[0]
print("target:", repr(os.path.basename(p)))

with open(p, "rb") as f:
    hdr = f.read(32)
    jlen = struct.unpack("<Q", hdr[8:16])[0]
    buf = f.read(jlen + 64)
j, _ = json.JSONDecoder().raw_decode(buf.decode("utf-8", errors="replace").lstrip())

objs = j["objects"]
print("kinds:", dict(collections.Counter(o.get("kind") for o in objs)))
print("encodings:", dict(collections.Counter(o.get("encoding") for o in objs)))
keys = collections.Counter()
for o in objs:
    keys.update(o.keys())
print("object keys:", dict(keys))

for kind in sorted({o.get("kind") for o in objs}):
    ex = [o for o in objs if o.get("kind") == kind][:3]
    print("-- kind=%s n=%d" % (kind, sum(1 for o in objs if o.get("kind") == kind)))
    for o in ex:
        print("   ", json.dumps(o, ensure_ascii=False)[:360])

names = [o.get("id", "") for o in objs]
lay = [n for n in names if re.search(r"(blk|layers)\.\d+", n)]
print("layer-tensors n=", len(lay))
for n in lay[:10]:
    print("   ", n)
q = [o for o in objs if any("quant" in k.lower() or "dtype" in k.lower() or "shape" in k.lower() for k in o)]
print("quant-meta n=", len(q))
for o in q[:4]:
    print("   Q:", json.dumps(o, ensure_ascii=False)[:360])
print("proposal domain:", json.dumps((j.get("components", {}).get("text", {}) or {}).get("proposal"), ensure_ascii=False)[:300])
