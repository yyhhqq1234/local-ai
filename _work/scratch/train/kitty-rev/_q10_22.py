# -*- coding: utf-8 -*-
"""看清 V6.1 要攻的两道题到底要什么"""
import json
rows=[json.loads(l) for l in open("data/eval.jsonl",encoding="utf-8") if l.strip()]
for idx in (10, 22):
    r = rows[idx-1]
    m = r.get("meta") or {}
    print("="*70)
    print(f"题{idx}  cat={m.get('cat')}  outcome={m.get('outcome')}")
    print("-"*70)
    u = next((x.get("content") for x in r["messages"] if x.get("role")=="user"), "")
    print("【问】")
    print(u[:1200])
    print("\n【meta 键】", list(m.keys()))
    # 参考答案
    a = next((x.get("content") for x in reversed(r["messages"]) if x.get("role")=="assistant"), "")
    print("\n【参考答案】（判据从这里抽事实）")
    print(a[:1800])
    print(f"\n参考答案长度 {len(a)}")
    for k in ("ref","refTokens","facts","expect"):
        if k in m: print(f"meta.{k} = {m[k]}")
