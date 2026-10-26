import json
b=json.load(open("logs/v5/JUDGE-ALL23-V5-REALSCHEMA.json",encoding="utf-8"))
for d in b["detail"]:
    if d["i"] in (1,2,18,19,21):
        print(f"--- 题{d['i']} [{d['cat']}] pass={d['pass']} chars={d['chars']} calls={d['calls']}")
        print("   why:", d["why"])
        for t in d["traj"]:
            print("   ", t)
