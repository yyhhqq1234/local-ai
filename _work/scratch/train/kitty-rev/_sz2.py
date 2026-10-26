import json
d=json.load(open("data/intent3/v6-mix/tools.json",encoding="utf-8"))
raw=json.dumps(d["function_schemas"],ensure_ascii=False)
print("function_schemas JSON 字符数:", len(raw))
print("粗估 token:", len(raw)//3, "-", len(raw)//2)
# 最长的 5 个 description
items=sorted(d["tools"], key=lambda t: -len(t.get("description") or ""))[:5]
for t in items:
    print(f"  {t['name']:<20} desc {len(t['description'])} 字符")
print("\n平均 desc 长度:", sum(len(t.get('description') or '') for t in d["tools"])//len(d["tools"]))
