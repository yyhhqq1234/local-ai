import json, os, struct, sys

d = sys.argv[1]
files = sorted(f for f in os.listdir(d) if f.endswith(".safetensors"))
wm, total = {}, 0
for f in files:
    with open(os.path.join(d, f), "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]
        hdr = json.loads(fh.read(n))
    for k, v in hdr.items():
        if k == "__metadata__":
            continue
        wm[k] = f
        o = v["data_offsets"]
        total += o[1] - o[0]
out = os.path.join(d, "model.safetensors.index.json")
json.dump({"metadata": {"total_size": total}, "weight_map": wm}, open(out, "w"), indent=1)
print("shards=%d tensors=%d total=%d -> %s" % (len(files), len(wm), total, out))
