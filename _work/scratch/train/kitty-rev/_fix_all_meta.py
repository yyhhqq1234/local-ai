# -*- coding: utf-8 -*-
"""批量补齐：把 actions 枚举写进 description。
根因：模型的工具 schema 里 description 不说 action 枚举，模型只能猜；
     而 tool-route 判据要求命中 action 字面量 → 系统性必败。
证据：kitty_jadx 只补 description 就从 0/3 → 3/3（v5 权重未训练）。"""
import json
p = "data/intent3/v6-mix/tools.json"
d = json.load(open(p, encoding="utf-8"))
n_fixed = 0
detail = []
for t in d["tools"]:
    acts = t.get("actions") or []
    if len(acts) < 1:
        continue
    desc = t.get("description") or ""
    low = desc.lower()
    miss = [a for a in acts if a.lower() not in low]
    if not miss:
        continue  # 已经写了
    add = "｜action 枚举：" + " / ".join(acts)
    if "action 枚举" in desc:
        # 已有枚举但漏了几个，追加缺失项
        add = "（补充：" + " / ".join(miss) + "）"
    t["description"] = desc.rstrip("）)") + add
    n_fixed += 1
    detail.append(t["name"])
# 同步 function_schemas
by = {t["name"]: t["description"] for t in d["tools"]}
for s in d["function_schemas"]:
    if s["function"]["name"] in by:
        s["function"]["description"] = by[s["function"]["name"]]
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"补齐 {n_fixed} 个工具的 description")
print("修复清单:", ", ".join(detail[:30]))
# 复扫
d2 = json.load(open(p, encoding="utf-8"))
still = []
for t in d2["tools"]:
    acts = t.get("actions") or []
    if len(acts) < 2: continue
    low = (t.get("description") or "").lower()
    if all(a.lower() not in low for a in acts):
        still.append(t["name"])
print(f"\n复扫：actions 完全没在 description 出现的工具 = {len(still)} 个")
if still: print("  剩余:", still)
