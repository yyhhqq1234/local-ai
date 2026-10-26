import json, re
lines = open("logs/v6/base-all23-fixed.log", encoding="utf-8", errors="replace").read().splitlines()
r1 = []
inr1 = False
for L in lines:
    if "===== 第 1/3 轮" in L: inr1 = True; continue
    if "===== 第 2/3 轮" in L: inr1 = False
    if inr1:
        m = re.match(r"\[(\d+)/23\]\s+(\S+)\s+(PASS|FAIL)\s+(.*)", L)
        if m: r1.append({"i": int(m.group(1)), "cat": m.group(2), "pass": m.group(3)=="PASS", "why": m.group(4).strip()})
cats = {}
for d in r1:
    cats.setdefault(d["cat"], {"pass":0,"total":0})
    cats[d["cat"]]["total"] += 1
    if d["pass"]: cats[d["cat"]]["pass"] += 1
out = {"judge":"v6-agent-loop","source":"round1-only (round2 进程僵死，未完成)",
       "repeat":3,"note":"单轮口径，非多数票；第2/3轮因进程僵死于 02:37 中断，按时间预算不重跑",
       "pass": sum(1 for d in r1 if d["pass"]), "total": len(r1),
       "byCat": cats, "detail": r1}
json.dump(out, open("logs/v6/BASE-ALL23-FIXEDSCHEMA-R1.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"定稿: {out['pass']}/{out['total']} = {out['pass']/out['total']*100:.1f}%")
for k,v in sorted(cats.items(), key=lambda x:-x[1]["total"]):
    print(f"  {k:<22} {v['pass']}/{v['total']}")
print("→ logs/v6/BASE-ALL23-FIXEDSCHEMA-R1.json")
