# -*- coding: utf-8 -*-
import json, os
def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
o = load("logs/v6/BASE-TOOLROUTE4.json")
n = load("logs/v6/BASE-TOOLROUTE4-NEWSCHEMA.json")
print("旧 schema:", "有" if o else "无", "| 新 schema:", "有" if n else "无")
if not n:
    print("新基线还没出，等")
    raise SystemExit(0)
print(f"\n{'题':<4}{'工具':<20}{'旧schema':<18}{'新schema':<18}Δ")
for a, b in zip(o["detail"], n["detail"]):
    tool = (b.get("why") or "").split(" ")[0].replace("tool=", "")
    print(f"{b['i']:<4}{tool:<20}{str(a['pass'])+' '+a.get('votes',''):<18}{str(b['pass'])+' '+b.get('votes',''):<18}{int(b['pass'])-int(a['pass']):+d}")
print(f"\n总计  旧 {o['pass']}/4  →  新 {n['pass']}/4   （repeat={n.get('repeat')}）")
print("\n新 schema 逐题 why:")
for d in n["detail"]:
    print(f"  题{d['i']} pass={d['pass']} votes={d.get('votes')}  {d.get('why')}")
