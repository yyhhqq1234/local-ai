# -*- coding: utf-8 -*-
"""查另两个稳败工具的元数据是否同样矛盾"""
import json
d = json.load(open("data/intent3/v6-mix/tools.json", encoding="utf-8"))
by = {t["name"]: t for t in d["tools"]}
for nm in ("kitty_rea_trace", "kitty_rea_method", "kitty_rea", "kitty_rea_function",
           "kitty_engines", "kitty_loop_status", "reverse_add_target"):
    t = by.get(nm)
    if not t:
        print(f"{nm:<22} 不在 tools.json"); continue
    print(f"{nm:<22} actions={t['actions']}")
    print(f"{'':22} desc={t.get('description','')[:110]}")
    print(f"{'':22} params={list((t.get('params') or {}).keys())}")
# 找出所有「actions 有 ≥2 个自定义枚举、但 description 里一个都没提」的
print("\n=== 同族隐患扫描（actions 未在 description 出现）===")
bad = []
for t in d["tools"]:
    acts = t.get("actions") or []
    if len(acts) < 2: continue
    desc = (t.get("description") or "").lower()
    miss = [a for a in acts if a.lower() not in desc]
    if len(miss) == len(acts):
        bad.append((t["name"], acts, t.get("description","")[:60]))
for nm, acts, desc in bad:
    print(f"  {nm:<24} actions={acts}  desc={desc}")
print(f"\n共 {len(bad)} 个工具 actions 完全没在 description 出现")
