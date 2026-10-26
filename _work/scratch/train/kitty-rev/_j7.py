import json
d=json.load(open("logs/v5/JUDGE7-V5-patched.json",encoding="utf-8"))
print("pass",d.get("pass"),"/",d.get("total"))
det=d.get("detail")
print("detail type:",type(det).__name__)
if isinstance(det,list):
    for i,r in enumerate(det,1):
        print(f"--- #{i} ---")
        for k,v in r.items():
            s=str(v)
            if len(s)>400: s=s[:400]+"…"
            print(f"  {k}: {s}")
