import json, sys, os

base = r"D:\BaiduNetdiskDownload\Local-AI\train\data"

# 1) v4 lexicon structure
d = json.load(open(os.path.join(base, "nsfw-lexicon-v4.json"), encoding="utf-8"))
print("=== nsfw-lexicon-v4.json ===")
print("top keys:", list(d.keys()) if isinstance(d, dict) else "list")
for k, v in d.items():
    if isinstance(v, dict):
        sub = v.get("terms", {})
        print(f"  {k}: {len(sub)} terms, desc={v.get('desc','')[:60]}")
    elif isinstance(v, list):
        print(f"  {k}: list[{len(v)}]")
    else:
        print(f"  {k}: {type(v).__name__}")

# 2) raw nsfw.jsonl sample
print("\n=== nsfw.jsonl (raw) ===")
with open(os.path.join(base, "nsfw.jsonl"), encoding="utf-8") as f:
    n = 0
    for line in f:
        n += 1
        if n <= 3:
            obj = json.loads(line)
            print(f"[{n}] keys={list(obj.keys())[:10]}")
            # show first 200 chars of each string field
            for kk, vv in list(obj.items())[:6]:
                if isinstance(vv, str):
                    print(f"  {kk}: {vv[:150]!r}")
                elif isinstance(vv, list):
                    print(f"  {kk}: list[{len(vv)}]")
                elif isinstance(vv, dict):
                    print(f"  {kk}: dict keys={list(vv.keys())[:8]}")
    print(f"  total lines: {n}")
