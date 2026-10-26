# -*- coding: utf-8 -*-
"""修 kitty_jadx 的元数据矛盾：description 说 passthrough，actions 却是三个自定义枚举。
   模型信了 description 就不列枚举 → tool-route 判据必挂。"""
import json
p = "data/intent3/v6-mix/tools.json"
d = json.load(open(p, encoding="utf-8"))
fixed = []
for t in d["tools"]:
    if t["name"] == "kitty_jadx":
        old = t.get("description", "")
        t["description"] = ("APK Java decompile (jadx passthrough)｜"
                            "action 枚举：status / decompile / search（三个自定义动词，"
                            "不是 jadx CLI 参数；问「这个工具怎么用」时要列出这三个 action 名）")
        fixed.append((old, t["description"][:90]))
    # 同族问题：凡 actions 里有自定义枚举但 description 提到 passthrough 的，补上枚举说明
    if t["name"] in ("kitty_apktool", "kitty_frida", "kitty_ida", "kitty_ghidra") and "passthrough" in (t.get("description") or ""):
        acts = " / ".join(t.get("actions") or [])
        t["description"] = (t["description"] or "").rstrip("）)") + f"｜action 枚举：{acts}"
        fixed.append((t["name"], t["description"][:90]))
# 重建 function_schemas 里的 description
for s in d["function_schemas"]:
    nm = s["function"]["name"]
    for t in d["tools"]:
        if t["name"] == nm:
            s["function"]["description"] = t["description"]
            break
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"修改 {len(fixed)} 个工具的 description:")
for a, b in fixed:
    print(f"  旧: {a[:70]}")
    print(f"  新: {b}")
print("\n验证 kitty_jadx:")
for t in d["tools"]:
    if t["name"] == "kitty_jadx":
        print("  actions:", t["actions"])
        print("  description:", t["description"])
