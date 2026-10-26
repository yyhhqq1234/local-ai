import json
tj=json.load(open("data/intent3/v6-mix/tools.json",encoding="utf-8"))
raw=json.dumps(tj["function_schemas"],ensure_ascii=False)
print("60 工具 schema JSON 字符数:", len(raw))
print("粗估 token:", len(raw)//3, "-", len(raw)//2)
