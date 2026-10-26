import json
d=json.load(open(r"D:\BaiduNetdiskDownload\Local-AI\train\local-pack\qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer.conversion.json",encoding="utf-8"))
print("name:", d.get("name"))
print("provenance:", json.dumps(d.get("provenance"), ensure_ascii=False))
print("components:", list(d.get("components",{}).keys()))
for k,v in d["components"].items():
    cfg=v.get("config") or {}
    print(f"  {k}: arch={cfg.get('architectures')} type={cfg.get('model_type')}")
