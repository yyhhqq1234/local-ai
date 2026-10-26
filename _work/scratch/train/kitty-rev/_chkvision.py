import json
def get_json(path, limit=2000000):
    with open(path, "rb") as f:
        data = f.read(limit)
    i = data.find(b'{"components"')
    if i < 0: return None
    txt = data[i:].decode("utf-8", "ignore")
    obj, _ = json.JSONDecoder().raw_decode(txt)
    return obj
p = r"D:\BaiduNetdiskDownload\Local-AI\train\local-pack\qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer"
d = get_json(p)
comp = d.get("components") or {}
print("components keys =", list(comp.keys()))
if "vision" in comp:
    v = comp["vision"]
    print("  vision.config =", json.dumps(v.get("config"), ensure_ascii=False)[:300])
    print("  vision.target =", v.get("target"))
    print("  vision.resources =", list((v.get("resources") or {}).keys()))
else:
    print("  ❌ 无 vision 组件")
