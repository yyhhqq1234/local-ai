# -*- coding: utf-8 -*-
import json
rows = [json.loads(l) for l in open("data/eval-key6.jsonl", encoding="utf-8") if l.strip()]
print("rows =", len(rows))
for i, r in enumerate(rows, 1):
    m = r.get("meta") or {}
    print("  key%d  cat=%-18s tool=%s" % (i, m.get("cat"), m.get("tool", "")))
# 与基线、V6 复测的题号映射
base = json.load(open("logs/v6/BASE-ALL23-FIXEDSCHEMA-R1.json", encoding="utf-8"))
v6 = json.load(open("logs/v6/JUDGE-V6-KEY6.json", encoding="utf-8"))
print("\n基线 3 道 FAIL:")
for d in base["detail"]:
    if not d["pass"]:
        print("  题%-3d [%s] %s" % (d["i"], d["cat"], d["why"][:60]))
print("\nV6 复测 6 题:")
for d in v6["detail"]:
    print("  key%-2d [%-18s] pass=%-5s votes=%s" % (d["i"], d["cat"], d["pass"], d.get("votes")))
