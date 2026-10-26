import sys, json, os
sys.path.insert(0, "eval")
import eval_kitty_v5 as V5
print("v5 TOOLS 数量:", len(V5.TOOLS))
for t in V5.TOOLS:
    fn = t.get("function") or t
    print("  ", fn.get("name"), "|", str(fn.get("description"))[:40])
