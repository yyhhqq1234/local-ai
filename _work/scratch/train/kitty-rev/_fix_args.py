# -*- coding: utf-8 -*-
"""本地执行方案 A：arguments str→dict，并做渲染对照验证"""
import json, hashlib
src = "data/intent3/v6-mix/train.final.jsonl"
dst = "data/intent3/v6-mix/train.final.dictargs.jsonl"
n = fixed = bad = 0
with open(src, encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
    for line in fi:
        line = line.strip()
        if not line: continue
        d = json.loads(line); n += 1
        for m in d.get("messages") or []:
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                a = fn.get("arguments")
                if isinstance(a, str):
                    try:
                        fn["arguments"] = json.loads(a); fixed += 1
                    except Exception:
                        bad += 1
        fo.write(json.dumps(d, ensure_ascii=False) + "\n")
print(f"rows={n} fixed={fixed} bad={bad} -> {dst}")
print("src md5:", hashlib.md5(open(src,'rb').read()).hexdigest())
print("dst md5:", hashlib.md5(open(dst,'rb').read()).hexdigest())

# 渲染对照（jinja2 模拟模板的 |items 用法）
import jinja2
tpl = jinja2.Template(
  "{% for m in messages %}{% if m.tool_calls %}{% for tc in m.tool_calls %}"
  "<c>{{tc['function']['name']}}({% for k,v in tc['function']['arguments']|items %}{{k}}={{v}};{% endfor %})</c>"
  "{% endfor %}{% endif %}{% endfor %}")
row = json.loads(open(src, encoding="utf-8").readline())
row2 = json.loads(open(dst, encoding="utf-8").readline())
for tag, r in (("原始(str)", row), ("转换(dict)", row2)):
    try:
        out = tpl.render(messages=r["messages"])
        print(f"  {tag}: OK len={len(out)}")
    except Exception as e:
        print(f"  {tag}: {type(e).__name__}: {e}")

# 类型统计复核
types = {"str":0, "dict":0, "other":0}
for line in open(dst, encoding="utf-8"):
    d = json.loads(line)
    for m in d.get("messages") or []:
        for tc in (m.get("tool_calls") or []):
            a = (tc.get("function") or {}).get("arguments")
            types["dict" if isinstance(a, dict) else ("str" if isinstance(a, str) else "other")] += 1
print("转换后 arguments 类型统计:", types)
